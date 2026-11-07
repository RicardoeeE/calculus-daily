// Sesion de hoy en la ventana: «Hoy solo 2», «No se por donde empezar», confirmacion
// de la solucion, practica de memoria y formulas en pistas y solucion. Solo interfaz: todo pasa por
// window.pywebview.api (calculo/ventana.py, clase API), que llama al motor.
// Textos con textContent; formulas con KaTeX (trust:false, maxExpand pequeno).
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const KATEX = { throwOnError: false, trust: false, maxExpand: 50, maxSize: 20, strict: "ignore" };
  const ESPERA_LECTURA = 300;

  let api = null;
  let datos = { causas: [], limite: 200 };
  let cola = [];
  let indice = 0;
  let hechos = 0;
  let actual = null;      // ejercicio en curso (dict de la cola)
  let estado = {};        // confianza, pistas, fallos, ultima, rendido...
  let tecnicasVistas = new Set();
  let sensacionElegida = null;
  let modoExamen = false; // la cola es la extra del proximo examen
  let escapePulsado = false;
  let volverAlEjercicio = false;   // el ejemplo de «No se por donde empezar» vuelve al mismo ejercicio
  const violaciones = [];

  // ---------- utilidades ----------

  const CAUSA_ESCRITA = {
    1: "No sabía por dónde empezar",
    2: "Elegí la técnica, pero me lié en un paso",
    3: "Álgebra o una cuenta",
    4: "Signo o constante",
    5: "Creo que estaba bien",
  };

  // Por que sale este ejercicio, dicho sin la jerga del motor.
  const COMO_SE_LLAMA = {
    nueva: "Primer ejercicio de",
    repaso: "Repaso de",
    refuerzo: "Refuerzo de",
    examen: "Para el examen:",
    simulacro: "Simulacro:",
  };

  // Atajos que valen en cada pantalla.
  const ATAJOS = {
    ejemplo: "Esc para salir",
    confianza: "Teclas 1 a 5 para elegir, Esc para salir",
    respuesta: "Enter para comprobar, Esc para salir",
    causa: "Teclas 1 a 4 para elegir, Esc para salir",
    hecho: "Enter para seguir, Esc para salir",
    final: "Teclas 1 a 5 para elegir, Esc para salir",
    resumen: "Esc para cerrar",
    vacia: "Esc para cerrar",
  };

  function fase(nombre) {
    document.body.dataset.fase = nombre;
    if (nombre in ATAJOS) $("pie").textContent = ATAJOS[nombre];
    ajustarFormulas();
  }

  function mostrarPantalla(id) {
    for (const p of document.querySelectorAll(".pantalla")) p.hidden = p.id !== id;
  }

  function aviso(texto) {
    const el = $("aviso");
    el.textContent = texto;
    el.hidden = false;
    clearTimeout(aviso.t);
    aviso.t = setTimeout(() => { el.hidden = true; }, 8000);
  }

  // Cada llamada a Python: un ok:false se ensena (discreto) y queda en el log de Python.
  async function llamar(metodo, ...args) {
    let r;
    try {
      r = await api[metodo](...args);
    } catch (e) {
      r = { ok: false, error: String(e && e.message || e) };
      try { api.anotar_error(metodo + ": " + r.error); } catch (_) { /* sin puente */ }
    }
    if (!r || r.ok === false) {
      aviso("Algo no ha ido bien (" + metodo + "): " + ((r && (r.error || r.mensaje)) || "sin respuesta") +
            ". Lo registrado está guardado.");
    }
    return r || { ok: false };
  }

  function katex_en(el, tex, display) {
    el.textContent = "";
    try {
      window.katex.render(tex, el, Object.assign({ displayMode: !!display }, KATEX));
      return true;
    } catch (e) {
      el.textContent = tex;
      return false;
    }
  }

  // Una formula de los trozos: KaTeX estricto (si KaTeX no la entiende, se ensena la
  // fuente en monoespaciada: nunca se pierde nada). Las fracciones van a tamano
  // completo (\displaystyle), no encogidas dentro de la linea.
  function formula(tex, fuente, display) {
    const span = document.createElement("span");
    span.className = display ? "formula formula-principal" : "formula";
    try {
      const t = !display && tex.indexOf("\\frac") >= 0 ? "\\displaystyle " + tex : tex;
      window.katex.render(t, span, Object.assign({}, KATEX, { displayMode: !!display, throwOnError: true }));
    } catch (e) {
      const code = document.createElement("code");
      code.className = "mono";
      code.textContent = fuente || tex;
      span.textContent = "";
      span.appendChild(code);
    }
    return span;
  }

  // Trozos que prepara Python (calculo/latex.py, trozos): {texto} con textContent,
  // {texto, mono} en monoespaciada y {tex} con KaTeX. Nada de innerHTML.
  function anadirTrozos(el, trozos, plano) {
    if (!Array.isArray(trozos) || !trozos.length) {
      if (plano) el.appendChild(document.createTextNode(String(plano)));
      return;
    }
    for (const t of trozos) {
      if (typeof t.tex === "string") {
        el.appendChild(formula(t.tex, t.fuente, false));
      } else if (t.mono) {
        const code = document.createElement("code");
        code.className = "mono";
        code.textContent = String(t.texto || "");
        el.appendChild(code);
      } else {
        el.appendChild(document.createTextNode(String(t.texto || "")));
      }
    }
  }

  function pintarTrozos(el, trozos, plano) {
    el.textContent = "";
    anadirTrozos(el, trozos, plano);
  }

  // Enunciado: la formula principal en grande (display) y, alrededor, sus textos en trozos.
  function pintarEnunciado(antes, centro, despues, d) {
    pintarTrozos(antes, d.enunciado_antes_trozos, d.enunciado_antes || "");
    centro.textContent = "";
    centro.classList.toggle("enunciado-formula", !!d.enunciado_latex);
    centro.style.fontSize = "";
    if (d.enunciado_latex) {
      centro.appendChild(formula(d.enunciado_latex, d.enunciado, true));
      pintarTrozos(despues, d.enunciado_despues_trozos, d.enunciado_despues || "");
    } else {
      pintarTrozos(centro, d.enunciado_trozos, d.enunciado);
      despues.textContent = "";
      antes.textContent = "";
    }
  }

  // Una formula muy larga baja de tamano para caber, hasta un minimo; si aun no cabe, se desplaza.
  function ajustarFormulas() {
    for (const el of document.querySelectorAll(".enunciado-formula")) {
      if (!el.offsetParent) continue;
      el.style.fontSize = "";
      if (el.scrollWidth <= el.clientWidth) continue;
      const actual = parseFloat(getComputedStyle(el).fontSize);
      el.style.fontSize = Math.max(19, Math.floor(actual * el.clientWidth / el.scrollWidth)) + "px";
    }
  }

  function anadirLinea(el, texto, trozos) {
    const div = document.createElement("div");
    pintarTrozos(div, trozos, texto);
    el.appendChild(div);
  }

  function lista(el, elementos) {
    el.textContent = "";
    for (const t of elementos) {
      const li = document.createElement("li");
      li.textContent = t;
      el.appendChild(li);
    }
  }

  function progreso() {
    const total = cola.length ? cola[0].total : 0;
    const n = actual ? actual.numero : total;
    $("progreso-texto").textContent = total ? "Ejercicio " + n + " de " + total : "";
    // Lo hecho antes de abrir la ventana (terminal o modo revisor) puede estar en medio de la
    // cola: cuenta lo que ya no esta pendiente (total - pendientes), no la posicion.
    const hechasAntes = total ? total - cola.length : 0;
    const pct = total ? Math.min(100, Math.round(100 * (hechasAntes + hechos) / total)) : 0;
    $("barra-relleno").style.width = pct + "%";
    $("barra").setAttribute("aria-valuenow", String(pct));
  }

  // ---------- arranque ----------

  async function empezar() {
    api = window.pywebview.api;
    const ini = await llamar("inicio");
    if (ini.ok) {
      datos = ini;
      if (ini.revision && ini.revision.length) {
        lista($("revision-lineas"), ini.revision);
        $("aviso-revision").hidden = false;
      }
    }
    const r = await llamar("cola");
    if (!r.ok) {
      $("vacia-titulo").textContent = "No se pudo preparar la sesión";
      $("vacia-texto").textContent = "Cierra la ventana y vuelve a abrir Practicar; si sigue igual, " +
        "practica en la terminal con otras-opciones\\Terminal.bat.";
      mostrarPantalla("pantalla-vacia");
      fase("vacia");
      return;
    }
    cola = r.ejercicios || [];
    construirCausas();
    $("solo-dos").hidden = !!datos.minimo || cola.length <= 2;
    if (!cola.length) {
      botonesExamen();
      mostrarPantalla("pantalla-vacia");
      fase("vacia");
      return;
    }
    indice = 0;
    abrirEjercicio();
  }

  // ---------- modo examen ----------

  function textoFaltan(n) {
    return n <= 0 ? "es hoy" : (n === 1 ? "falta 1 día" : "faltan " + n + " días");
  }

  // El boton de arriba cambia entre las dos colas; se ve entre ejercicios, nunca durante uno.
  function botonesExamen() {
    const ex = datos.examen;
    const b = $("modo-examen");
    b.hidden = !ex;
    if (!ex) return;
    b.textContent = modoExamen ? "Volver a la sesión de hoy" : "Preparar el " + ex.corto + " (" + textoFaltan(ex.faltan) + ")";
    const mas = (modoExamen ? "Otros 5 de " : "5 más de ") + ex.corto;
    $("mas-examen").textContent = mas;
    $("mas-examen").hidden = false;
    $("vacia-examen").textContent = mas;
    $("vacia-examen").hidden = modoExamen;   // en examen, si esta vacia es que no quedan
  }

  async function cambiarModo(examen) {
    if (!["leccion", "ejemplo", "confianza", "final", "vacia"].includes(document.body.dataset.fase)) return;
    const r = await llamar(examen ? "examen" : "cola");
    if (!r.ok) {
      aviso("No se pudo cambiar de sesión. Sigue con la que tienes.");
      return;
    }
    modoExamen = examen;
    $("titulo").textContent = examen ? "Preparar " + datos.examen.nombre : "Sesión de hoy";
    cola = r.ejercicios || [];
    tecnicasVistas = new Set();
    indice = 0;
    hechos = 0;
    $("solo-dos").hidden = examen || !!datos.minimo || cola.length <= 2;
    if (!cola.length) {
      actual = null;
      progreso();
      botonesExamen();
      $("vacia-titulo").textContent = examen ? "No quedan ejercicios de este examen" : "Hoy ya está todo hecho";
      $("vacia-texto").textContent = examen ? "Ya has hecho todos los que hay por hoy."
        : "No queda nada en la cola de hoy. Buen trabajo.";
      mostrarPantalla("pantalla-vacia");
      fase("vacia");
      return;
    }
    abrirEjercicio();
  }

  // «Hoy solo 2»: el dia minimo del motor (como `ventana --minimo`). Solo al empezar.
  async function soloDos() {
    if (hechos > 0 || !["leccion", "ejemplo", "confianza"].includes(document.body.dataset.fase)) return;
    $("solo-dos").hidden = true;
    const r = await llamar("minimo");
    if (!r.ok) return;
    cola = r.ejercicios || [];
    tecnicasVistas = new Set();
    indice = 0;
    if (!cola.length) {
      actual = null;
      progreso();
      $("vacia-titulo").textContent = "Hoy ya cuenta";
      $("vacia-texto").textContent = "Los 2 del día mínimo ya están hechos.";
      mostrarPantalla("pantalla-vacia");
      fase("vacia");
      return;
    }
    abrirEjercicio();
  }

  function construirCausas() {
    const cont = $("causas");
    cont.textContent = "";
    for (const c of datos.causas || []) {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.causa = c.clave;
      b.textContent = c.clave + ". " + (CAUSA_ESCRITA[c.clave] || c.texto);
      b.addEventListener("click", () => elegirCausa(c.clave));
      cont.appendChild(b);
    }
  }

  // ---------- ejemplo resuelto (completo o con huecos) ----------

  async function abrirEjercicio() {
    actual = cola[indice];
    estado = { confianza: null, pistas: actual.pistas_vistas || 0, fallos: actual.fallos || 0,
               ultima: null, rendido: false, reclamo: false, respuesta: null,
               solucion: !!actual.solucion_disponible, ocupado: false };
    progreso();
    botonesExamen();
    const ej = actual.ejemplo;
    if (ej && !tecnicasVistas.has(ej.tecnica)) {
      tecnicasVistas.add(ej.tecnica);
      if (actual.leccion) {
        fase("carga");
        const r = await llamar("leccion", ej.tecnica);
        if (r.ok) {
          abrirLeccion(r.leccion, null);
          return;
        }
      }
      ensenarEjemplo(ej);
    } else {
      ensenarEjercicio();
    }
  }

  function ensenarEjemplo(ej) {
    const conHuecos = !!ej.huecos;
    $("ejemplo-titulo").textContent = conHuecos
      ? "Ejemplo con huecos de " + (ej.nombre || ej.tecnica) + ": destapa los pasos o escribe el resultado. No lleva nota."
      : (volverAlEjercicio ? "Ejemplo resuelto de " + (ej.nombre || ej.tecnica) + ": léelo y vuelve a tu ejercicio"
                           : "Antes, un ejemplo resuelto de " + (ej.nombre || ej.tecnica));
    const idea = $("ejemplo-idea");
    idea.textContent = "";
    if (ej.idea) {
      idea.appendChild(document.createTextNode("Cuándo usar " + (ej.nombre || ej.tecnica) + ": "));
      anadirTrozos(idea, ej.idea_trozos, ej.idea);
    }
    pintarEnunciado($("ejemplo-enunciado-antes"), $("ejemplo-enunciado"), $("ejemplo-enunciado-despues"), ej);
    const ol = $("ejemplo-pasos");
    ol.textContent = "";
    const ocultos = ej.pasos_ocultos || [];
    const ocultosTrozos = ej.ocultos_trozos || [];
    let k = 0;
    ej.pasos.forEach((paso, i) => {
      const li = document.createElement("li");
      if (paso === "____" && k < ocultos.length) {
        // El hueco es un boton en su sitio: al pulsarlo se destapa ese paso.
        const j = k++;
        const b = document.createElement("button");
        b.type = "button";
        b.className = "hueco";
        b.textContent = "Paso oculto: piénsalo y pulsa para destaparlo";
        b.addEventListener("click", () => { pintarTrozos(li, ocultosTrozos[j], ocultos[j]); });
        li.appendChild(b);
      } else {
        pintarTrozos(li, (ej.pasos_trozos || [])[i], paso);
      }
      ol.appendChild(li);
    });
    $("ejemplo-campo").hidden = !conHuecos;
    $("ejemplo-respuesta").value = "";
    $("ejemplo-mensaje").textContent = "";
    const res = $("ejemplo-resultado");
    res.textContent = "Resultado: ";
    anadirTrozos(res, ej.resultado_trozos, ej.resultado);
    $("ejemplo-resultado").hidden = conHuecos;
    $("ejemplo-seguir").textContent = volverAlEjercicio ? "Volver al ejercicio" : "Seguir con el ejercicio";
    mostrarPantalla("pantalla-ejemplo");
    fase("ejemplo");
    (conHuecos ? $("ejemplo-respuesta") : $("ejemplo-seguir")).focus();
  }

  // ---------- leccion: teoria, ejemplos y ejemplo guiado; sin nota ni registro ----------

  let leccion = null;       // { datos, etapa, volver, paso, acertados }
  const ETAPAS = ["teoria", "ejemplos", "guiado"];

  function abrirLeccion(datosLeccion, volver) {
    leccion = { datos: datosLeccion, etapa: 0, volver, paso: 0, resuelto: false };
    $("leccion-tema").textContent = datosLeccion.tema || "";
    $("leccion-titulo").textContent = datosLeccion.titulo || "";
    $("leccion-saltar").textContent = volver ? "Volver al ejercicio" : "Ir directo al ejercicio";
    mostrarPantalla("pantalla-leccion");
    fase("leccion");
    pintarLeccion();
  }

  function salirDeLeccion() {
    if (!leccion) return;
    const volver = leccion.volver;
    leccion = null;
    if (volver) {
      mostrarPantalla("pantalla-ejercicio");
      fase(volver);
      (volver === "respuesta" ? $("respuesta") : $("bloque-confianza")).focus();
    } else {
      ensenarEjercicio();
    }
  }

  function bloque(padre, titulo, clase) {
    const s = document.createElement("section");
    s.className = "bloque " + (clase || "");
    if (titulo) {
      const h = document.createElement("h3");
      h.textContent = titulo;
      s.appendChild(h);
    }
    padre.appendChild(s);
    return s;
  }

  function parrafo(padre, trozos, clase) {
    const p = document.createElement("p");
    if (clase) p.className = clase;
    pintarTrozos(p, trozos, "");
    padre.appendChild(p);
    return p;
  }

  function listaTrozos(padre, etiqueta, items) {
    const l = document.createElement(etiqueta);
    l.className = "pasos";
    for (const t of items || []) {
      const li = document.createElement("li");
      pintarTrozos(li, t, "");
      l.appendChild(li);
    }
    padre.appendChild(l);
    return l;
  }

  function pintarLeccion() {
    const d = leccion.datos;
    const etapa = ETAPAS[leccion.etapa];
    for (const li of document.querySelectorAll(".hitos li")) {
      const i = ETAPAS.indexOf(li.dataset.etapa);
      li.classList.toggle("actual", i === leccion.etapa);
      li.classList.toggle("hecho", i < leccion.etapa);
    }
    const c = $("leccion-cuerpo");
    c.textContent = "";
    if (etapa === "teoria") {
      parrafo(bloque(c, "Para qué sirve"), d.que_es);
      parrafo(bloque(c, "Cómo reconocerla"), d.reconocer);
      parrafo(bloque(c, "Forma tipo", "forma-tipo"), d.forma, "forma");
      listaTrozos(bloque(c, "Cómo aplicarla"), "ol", d.pasos);
      if (d.ojo && d.ojo.length) listaTrozos(bloque(c, "Ojo", "ojo"), "ul", d.ojo);
    } else if (etapa === "ejemplos") {
      (d.ejemplo || []).forEach((ej, i) => {
        const s = bloque(c, "Ejemplo " + (i + 1), "ejemplo-leccion");
        parrafo(s, ej.enunciado, "enunciado-leccion");
        listaTrozos(s, "ol", ej.pasos);
        const r = parrafo(s, ej.resultado, "resultado");
        r.insertBefore(document.createTextNode("Resultado: "), r.firstChild);
      });
    } else {
      pintarGuiado(c, d.guiado);
    }
    $("leccion-atras").hidden = leccion.etapa === 0;
    actualizarSiguiente();
    window.scrollTo(0, 0);
    $("leccion-siguiente").focus({ preventScroll: true });   // cada parte se lee desde arriba
  }

  function actualizarSiguiente() {
    const b = $("leccion-siguiente");
    const etapa = ETAPAS[leccion.etapa];
    if (etapa === "teoria") {
      b.textContent = "Ver ejemplos";
    } else if (etapa === "ejemplos") {
      b.textContent = "Hacer uno guiado";
    } else {
      const pasos = leccion.datos.guiado.paso;
      const ultimo = leccion.paso >= pasos.length;
      b.textContent = ultimo ? (leccion.volver ? "Volver al ejercicio" : "Empezar el ejercicio") : "Siguiente paso";
      b.disabled = !ultimo && !leccion.resuelto;
      $("leccion-saltar").hidden = ultimo;
      return;
    }
    b.disabled = false;
    $("leccion-saltar").hidden = false;
  }

  function pintarGuiado(c, g) {
    const s = bloque(c, "Resuélvelo paso a paso. No lleva nota", "guiado");
    parrafo(s, g.enunciado, "enunciado-leccion");
    const hechos_ = document.createElement("ol");
    hechos_.className = "guiado-hechos";
    g.paso.slice(0, leccion.paso).forEach((p) => {
      const li = document.createElement("li");
      pintarTrozos(li, p.opciones.find((o) => o.correcta).texto, "");
      hechos_.appendChild(li);
    });
    if (hechos_.childNodes.length) s.appendChild(hechos_);
    if (leccion.paso >= g.paso.length) {
      parrafo(s, g.cierre, "guiado-cierre");
      return;
    }
    const p = g.paso[leccion.paso];
    const cab = document.createElement("p");
    cab.className = "etiqueta";
    cab.textContent = "Paso " + (leccion.paso + 1) + " de " + g.paso.length;
    s.appendChild(cab);
    parrafo(s, p.pregunta, "pregunta");
    const ops = document.createElement("div");
    ops.className = "opciones";
    ops.setAttribute("role", "group");
    const nota = document.createElement("p");
    nota.className = "opcion-nota";
    nota.setAttribute("aria-live", "polite");
    p.opciones.forEach((o) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "opcion";
      b.dataset.correcta = o.correcta ? "1" : "";
      pintarTrozos(b, o.texto, "");
      b.addEventListener("click", () => {
        pintarTrozos(nota, o.porque, "");
        nota.dataset.estado = o.correcta ? "bien" : "mal";
        b.classList.add(o.correcta ? "bien" : "mal");
        if (o.correcta) {
          for (const x of ops.querySelectorAll("button")) x.disabled = true;
          leccion.resuelto = true;
          actualizarSiguiente();
          $("leccion-siguiente").focus({ preventScroll: true });
        }
      });
      ops.appendChild(b);
    });
    s.appendChild(ops);
    s.appendChild(nota);
  }

  function leccionSiguiente() {
    if (document.body.dataset.fase !== "leccion" || !leccion) return;
    if (ETAPAS[leccion.etapa] === "guiado") {
      if (leccion.paso >= leccion.datos.guiado.paso.length) {
        salirDeLeccion();
        return;
      }
      if (!leccion.resuelto) return;
      leccion.paso += 1;
      leccion.resuelto = false;
    } else {
      leccion.etapa += 1;
    }
    pintarLeccion();
  }

  function leccionAtras() {
    if (document.body.dataset.fase !== "leccion" || !leccion || leccion.etapa === 0) return;
    leccion.etapa -= 1;
    leccion.paso = 0;
    leccion.resuelto = false;
    pintarLeccion();
  }

  async function verTeoria() {
    const f = document.body.dataset.fase;
    if (!["confianza", "respuesta"].includes(f) || !actual || !actual.leccion_disponible) return;
    const r = await llamar("leccion", actual.tecnica);
    if (r.ok) abrirLeccion(r.leccion, f);
  }

  function destaparTodo() {
    for (const b of $("ejemplo-pasos").querySelectorAll("button.hueco")) b.click();
    $("ejemplo-resultado").hidden = false;
  }

  async function comprobarEjemplo() {
    const t = $("ejemplo-respuesta").value.trim();
    const ej = actual.ejemplo;
    if (!t) { seguirTrasEjemplo(); return; }
    const r = await llamar("comprobar_ejemplo", ej.tecnica, t);
    if (!r.ok) return;
    if (r.error) {
      $("ejemplo-mensaje").textContent = "No lo leo: " + r.error + ".";
      return;
    }
    $("ejemplo-mensaje").textContent = r.correcto ? "Bien." : "No coincide; mira los pasos.";
    destaparTodo();
    $("ejemplo-seguir").focus();
  }

  function seguirTrasEjemplo() {
    if (!$("ejemplo-campo").hidden && $("ejemplo-resultado").hidden) {
      destaparTodo();           // primero se ve el final; el segundo Enter sigue
      $("ejemplo-seguir").focus();
      return;
    }
    if (volverAlEjercicio) {
      volverAlEjercicio = false;
      mostrarPantalla("pantalla-ejercicio");
      actualizarBotones();
      fase("respuesta");
      $("respuesta").focus();
      return;
    }
    ensenarEjercicio();
  }

  // ---------- el ejercicio ----------

  function ensenarEjercicio() {
    const e = actual;
    const nombre = e.tecnica_nombre || e.tecnica || "";
    const frase = ((COMO_SE_LLAMA[e.etiqueta || e.motivo] || "") + " " + nombre).replace(/\bde el\b/, "del").trim();
    $("ej-etiqueta").textContent = "";
    $("ej-tecnica").textContent = frase.charAt(0).toUpperCase() + frase.slice(1);
    $("enunciado").dataset.numero = "(" + (e.numero || indice + 1) + ")";
    $("ver-teoria").hidden = !e.leccion_disponible;
    pintarEnunciado($("enunciado-antes"), $("enunciado"), $("enunciado-despues"), e);
    const como = $("como-responder");
    como.textContent = "";
    if (e.como_responder) {
      como.appendChild(document.createTextNode("("));
      anadirTrozos(como, e.como_responder_trozos, e.como_responder);
      como.appendChild(document.createTextNode(")"));
    }
    for (const b of document.querySelectorAll("[data-confianza]")) b.classList.remove("elegido");
    $("bloque-confianza").hidden = false;
    $("bloque-respuesta").hidden = true;
    $("bloque-causa").hidden = true;
    $("bloque-hecho").hidden = true;
    $("respuesta").value = "";
    limpiarVistaPrevia();
    $("mensaje").textContent = "";
    $("pistas").textContent = "";
    $("solucion-texto").hidden = true;
    $("solucion-texto").textContent = "";
    $("confirmar-solucion").hidden = true;
    $("bloque-memoria").hidden = true;
    $("reescribir").hidden = false;
    $("memoria-campo").hidden = true;
    $("memoria").value = "";
    $("memoria-mensaje").textContent = "";
    $("ver-grafica").hidden = !e.grafica;
    actualizarBotones();
    mostrarPantalla("pantalla-ejercicio");
    fase("confianza");
    $("bloque-confianza").focus();
  }

  async function elegirConfianza(n) {
    if (document.body.dataset.fase !== "confianza") return;
    estado.confianza = n;
    $("solo-dos").hidden = true;
    $("modo-examen").hidden = true;
    for (const b of document.querySelectorAll("[data-confianza]")) {
      b.classList.toggle("elegido", b.dataset.confianza === String(n));
    }
    fase("mostrando");
    const r = await llamar("mostrar", actual.ficha, actual.semilla);   // el reloj lo lleva Python
    if (r.ok) {
      estado.pistas = Math.max(estado.pistas, r.pistas_vistas || 0);
      estado.fallos = Math.max(estado.fallos, r.fallos || 0);
      estado.solucion = !!r.solucion_disponible;
    }
    $("bloque-confianza").hidden = true;
    $("bloque-respuesta").hidden = false;
    actualizarBotones();
    fase("respuesta");
    $("respuesta").focus();
  }

  function actualizarBotones() {
    $("pista").disabled = estado.pistas >= 3;
    $("pista").textContent = estado.pistas >= 3 ? "No hay más pistas" : "Pista " + (estado.pistas + 1);
    $("ver-solucion").hidden = !estado.solucion;
    $("estaba-bien").hidden = !estado.ultima;
    // «No se por donde empezar»: antes de responder (sin fallos) y mientras no haya visto ya la pista 2.
    $("no-se").hidden = !!estado.ultima || estado.fallos > 0 || estado.pistas >= 2;
  }

  // ---------- vista previa neutra («He leído») ----------

  const previa = { temporizador: null, enVuelo: false, pendiente: false };

  function limpiarVistaPrevia() {
    clearTimeout(previa.temporizador);
    previa.pendiente = false;
    $("vista-previa-contenido").textContent = "";
    $("vista-previa").dataset.estado = "vacio";
    $("avisos-lectura").textContent = "";
  }

  function alEscribir() {
    clearTimeout(previa.temporizador);
    if (!$("respuesta").value.trim()) { limpiarVistaPrevia(); return; }
    $("vista-previa").dataset.estado = "esperando";
    previa.temporizador = setTimeout(pedirLectura, ESPERA_LECTURA);
  }

  async function pedirLectura() {
    if (previa.enVuelo) { previa.pendiente = true; return; }   // nunca bloquea: se pide la ultima al volver
    const texto = $("respuesta").value.slice(0, datos.limite || 200);
    if (!texto.trim() || !actual) return;
    previa.enVuelo = true;
    let r;
    try {
      r = await api.leer(texto, actual.ficha, actual.semilla);
    } catch (e) {
      r = null;
    }
    previa.enVuelo = false;
    if (previa.pendiente) { previa.pendiente = false; pedirLectura(); return; }
    if ($("respuesta").value.slice(0, datos.limite || 200) !== texto) return;   // ya ha cambiado
    pintarLectura(r);
  }

  function pintarLectura(r) {
    const cont = $("vista-previa-contenido");
    const caja = $("vista-previa");
    if (!r) { cont.textContent = "…"; caja.dataset.estado = "error"; return; }
    if (r.ok && r.latex) {
      katex_en(cont, r.latex, false);
      caja.dataset.estado = "leido";
    } else if (r.ok) {
      cont.textContent = r.leido;
      caja.dataset.estado = "leido";
    } else if (r.tope || r.disponible === false) {
      cont.textContent = r.error;
      caja.dataset.estado = "ilegible";
    } else {
      cont.textContent = "todavía no lo leo (" + (r.error || "…") + ")";
      caja.dataset.estado = "ilegible";
    }
    lista($("avisos-lectura"), r.avisos || []);
  }

  // ---------- comprobar, pistas, solucion, reclamo ----------

  async function comprobar() {
    if (document.body.dataset.fase !== "respuesta" || estado.ocupado) return;
    const t = $("respuesta").value.trim();
    if (!t) { $("respuesta").focus(); return; }
    estado.ocupado = true;
    const r = await llamar("comprobar", actual.ficha, actual.semilla, t);
    estado.ocupado = false;
    if (!r.ok) return;
    const m = $("mensaje");
    m.textContent = "";
    if (r.error) {
      m.textContent = "No lo leo: " + r.error + ".";
      return;
    }
    if (r.leido) anadirLinea(m, "He leído: " + r.leido, r.leido_trozos ? [{ texto: "He leído: " }].concat(r.leido_trozos) : null);
    (r.avisos || []).forEach((a, i) => {
      const tr = (r.avisos_trozos || [])[i];
      anadirLinea(m, "Ojo: " + a, tr ? [{ texto: "Ojo: " }].concat(tr) : null);
    });
    if (r.correcto) {
      anadirLinea(m, "Correcto.");
      estado.respuesta = t;
      await cerrarEjercicio();
      return;
    }
    estado.ultima = t;
    estado.fallos = r.fallos || estado.fallos + 1;
    estado.solucion = !!r.solucion_disponible;
    (r.diagnostico || []).forEach((d, i) => {
      const tr = (r.diagnostico_trozos || [])[i];
      anadirLinea(m, "El motor ve: " + d, tr ? [{ texto: "El motor ve: " }].concat(tr) : null);
    });
    if (estado.fallos <= 1) {
      anadirLinea(m, "No cuadra. Corrige y vuelve a escribir, pide una pista, o pulsa «Estaba bien» si crees que lo estaba.");
      anadirLinea(m, "(Si aciertas ahora, cuenta como «costó»: lo verás antes en el repaso.)");
    } else {
      anadirLinea(m, "No cuadra. Mejor pide una pista antes de seguir probando, o pulsa «Estaba bien» si crees que lo estaba.");
    }
    actualizarBotones();
    $("respuesta").focus();
    $("respuesta").select();
  }

  async function pedirPista() {
    if (document.body.dataset.fase !== "respuesta" || estado.pistas >= 3 || estado.ocupado) return;
    estado.ocupado = true;
    const nivel = estado.pistas + 1;
    const r = await llamar("pista", actual.ficha, actual.semilla, nivel);
    estado.ocupado = false;
    if (!r.ok) return;
    estado.pistas = nivel;
    estado.solucion = !!r.solucion_disponible;
    const li = document.createElement("li");
    pintarTrozos(li, r.trozos, r.texto);
    $("pistas").appendChild(li);
    actualizarBotones();
    $("respuesta").focus();
  }

  // «No se por donde empezar»: el ejemplo resuelto completo de la tecnica y vuelta al
  // mismo ejercicio. Cuenta como la pista 2 (el motor la anota): la solucion queda disponible.
  async function noSe() {
    if (document.body.dataset.fase !== "respuesta" || estado.ocupado) return;
    estado.ocupado = true;
    const r = await llamar("sin_saber_empezar", actual.ficha, actual.semilla);
    estado.ocupado = false;
    if (!r.ok) return;
    estado.pistas = Math.max(estado.pistas, r.pistas_vistas || 2);
    estado.solucion = true;
    if (r.ejemplo) {
      volverAlEjercicio = true;
      ensenarEjemplo(r.ejemplo);
      return;
    }
    (r.pistas || []).forEach((texto, i) => {
      const li = document.createElement("li");
      pintarTrozos(li, (r.pistas_trozos || [])[i], texto);
      $("pistas").appendChild(li);
    });
    actualizarBotones();
    $("respuesta").focus();
  }

  // «Ver la solucion» pide confirmacion: cuenta como no sabido.
  function pedirSolucion() {
    if (document.body.dataset.fase !== "respuesta" || !estado.solucion || estado.ocupado) return;
    $("confirmar-solucion").hidden = false;
    $("solucion-no").focus();
  }

  function seguirSinSolucion() {
    $("confirmar-solucion").hidden = true;
    $("respuesta").focus();
  }

  async function verSolucion() {
    if (document.body.dataset.fase !== "respuesta" || !estado.solucion || estado.ocupado) return;
    $("confirmar-solucion").hidden = true;
    estado.ocupado = true;
    const r = await llamar("solucion", actual.ficha, actual.semilla);
    estado.ocupado = false;
    if (!r.ok) return;
    estado.rendido = true;
    estado.pistas = 4;
    pintarTrozos($("solucion-texto"), r.trozos, r.texto);
    $("solucion-texto").hidden = false;
    await cerrarEjercicio();
  }

  async function estabaBien() {
    if (document.body.dataset.fase !== "respuesta" || !estado.ultima || estado.ocupado) return;
    estado.reclamo = true;
    estado.respuesta = estado.ultima;
    $("mensaje").textContent = "Anotado como reclamación: queda pendiente de revisar. No cuenta como fallo.";
    await cerrarEjercicio();
  }

  async function verGrafica() {
    const r = await llamar("ver", actual.ficha, actual.semilla);
    if (r.ok) $("mensaje").textContent = r.mensaje;
  }

  // ---------- causa, registro y siguiente ----------

  async function cerrarEjercicio() {
    fase("cerrando");
    $("comprobar").disabled = true;
    const c = await llamar("causa_necesaria", actual.ficha, actual.semilla, estado.rendido, estado.reclamo);
    if (c.ok && c.necesaria) {
      $("bloque-causa").hidden = false;
      fase("causa");
      $("bloque-causa").focus();
      return;
    }
    await registrar(null);
  }

  async function elegirCausa(clave) {
    if (document.body.dataset.fase !== "causa") return;
    $("bloque-causa").hidden = true;
    await registrar(clave);
  }

  async function registrar(causa) {
    fase("registrando");
    const r = await llamar("registrar", actual.ficha, actual.semilla, estado.confianza,
                           estado.respuesta, estado.rendido, causa, estado.reclamo);
    $("comprobar").disabled = false;
    let texto;
    if (!r.ok) {
      texto = "No se pudo registrar este ejercicio. Sigue con el siguiente; «doctor» dirá qué pasa.";
    } else if (r.ya_registrado) {
      texto = "Este ejercicio ya estaba registrado hoy: no se cuenta otra vez.";
    } else {
      texto = "Próximo repaso: " + r.proximo_texto;
    }
    hechos += 1;
    $("mensaje-hecho").textContent = texto;
    $("bloque-memoria").hidden = !(estado.rendido && r.ok && !r.ya_registrado);
    $("bloque-hecho").hidden = false;
    $("siguiente").textContent = indice + 1 < cola.length ? "Siguiente" : "Terminar";
    progreso();
    fase("hecho");
    $("siguiente").focus();
  }

  // Tras ver la solucion: reescribirla de memoria, sin nota (ya esta registrada).
  function reescribir() {
    $("solucion-texto").hidden = true;
    $("reescribir").hidden = true;
    $("memoria-campo").hidden = false;
    $("memoria").focus();
  }

  async function comprobarMemoria() {
    const t = $("memoria").value.trim();
    if (!t || !actual) return;
    const r = await llamar("practicar", actual.ficha, actual.semilla, t);
    if (!r.ok) return;
    const m = $("memoria-mensaje");
    if (r.error) { m.textContent = "No lo leo: " + r.error + "."; return; }
    m.textContent = r.correcto ? "Bien: ya la tienes. (Sin nota.)" : "No coincide todavía; mírala otra vez.";
    if (!r.correcto) $("solucion-texto").hidden = false;
    $("siguiente").focus();
  }

  function siguiente() {
    if (document.body.dataset.fase !== "hecho") return;
    indice += 1;
    if (indice < cola.length) {
      abrirEjercicio();
    } else {
      actual = null;
      progreso();
      botonesExamen();
      $("modo-examen").hidden = !modoExamen;   // al acabar la de hoy basta el boton de la tarjeta
      mostrarPantalla("pantalla-final");
      fase("final");
      $("final-preguntas").focus();
    }
  }

  // ---------- final ----------

  function elegirSensacion(n) {
    sensacionElegida = n;
    for (const b of document.querySelectorAll("[data-sensacion]")) {
      b.classList.toggle("elegido", b.dataset.sensacion === String(n));
    }
  }

  async function terminar() {
    if (document.body.dataset.fase !== "final") return;
    fase("terminando");
    $("terminar").disabled = true;
    const comentario = $("comentario").value.trim();
    const queja = $("queja").value.trim();
    if (sensacionElegida) {
      await llamar("sensacion", sensacionElegida, comentario);
    } else if (comentario) {
      await llamar("queja", comentario);
    }
    if (queja) await llamar("queja", queja);
    const r = await llamar("terminar");
    $("resumen").textContent = r.ok ? r.mensaje : "No se pudo escribir el diario; lo registrado está guardado.";
    $("final-preguntas").hidden = true;
    $("final-resumen").hidden = false;
    fase("resumen");
    $("salir-final").focus();
    vigilarSubida();
  }

  const ESTADOS_SUBIDA = {
    subiendo: "Guardado en tu equipo · subiendo…",
    subido: "Guardado en tu equipo · subido.",
    sin_red: "Guardado en tu equipo · sin red: se sube la próxima vez.",
    revisar: "Guardado en tu equipo · no se ha podido subir; se reintenta la próxima vez.",
    local: "Guardado en la carpeta de prueba (no se sube nada).",
    nada: "Guardado en tu equipo.",
    pendiente: "Guardado en tu equipo.",
  };

  async function vigilarSubida() {
    let r;
    try { r = await api.estado_subida(); } catch (e) { r = null; }
    const estadoSubida = r && r.estado || "pendiente";
    $("estado-subida").textContent = ESTADOS_SUBIDA[estadoSubida] || "Guardado en tu equipo.";
    if (estadoSubida === "subiendo") setTimeout(vigilarSubida, 1000);
  }

  // Antes de cerrar: si hay algo sin subir, la ventana ensena como acaba la subida
  // (con red o sin ella) en vez de una consola que se cierra sola.
  async function salir() {
    if (salir.enMarcha) return;
    salir.enMarcha = true;
    let r = null;
    if (document.body.dataset.fase !== "resumen") {
      try { r = await api.preparar_salida(); } catch (e) { r = null; }
    }
    if (r && r.ok && r.estado === "subiendo") {
      $("saliendo").hidden = false;
      const fin = Date.now() + 70000;
      while (r && r.estado === "subiendo" && Date.now() < fin) {
        $("saliendo-texto").textContent = ESTADOS_SUBIDA.subiendo;
        await new Promise((ok) => setTimeout(ok, 1000));
        try { r = await api.estado_subida(); } catch (e) { r = null; }
      }
      $("saliendo-texto").textContent = ESTADOS_SUBIDA[(r && r.estado) || "pendiente"] || ESTADOS_SUBIDA.pendiente;
      await new Promise((ok) => setTimeout(ok, 2500));
    }
    llamar("salir");
  }

  // ---------- teclado ----------

  function teclado(ev) {
    const f = document.body.dataset.fase;
    const enCampo = ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA");
    if (ev.key === "Escape") {
      ev.preventDefault();
      if (!$("confirmar-solucion").hidden) { seguirSinSolucion(); return; }
      if (f === "resumen" || f === "vacia" || escapePulsado) { salir(); return; }
      escapePulsado = true;
      aviso("Pulsa Esc otra vez para salir. Lo hecho queda guardado y puedes seguir después.");
      setTimeout(() => { escapePulsado = false; }, 4000);
      return;
    }
    if (f === "confianza" && /^[1-5]$/.test(ev.key)) {
      ev.preventDefault();
      elegirConfianza(Number(ev.key));
    } else if (f === "causa" && /^[1-4]$/.test(ev.key)) {
      ev.preventDefault();
      elegirCausa(ev.key);
    } else if (f === "final" && !enCampo && /^[1-5]$/.test(ev.key)) {
      ev.preventDefault();
      elegirSensacion(Number(ev.key));
    } else if (ev.key === "Enter" && !ev.shiftKey) {
      if (f === "respuesta" && ev.target === $("respuesta")) {
        ev.preventDefault();
        comprobar();
      } else if (f === "ejemplo" && ev.target === $("ejemplo-respuesta")) {
        ev.preventDefault();
        comprobarEjemplo();
      } else if (f === "hecho" && ev.target === $("memoria")) {
        ev.preventDefault();
        comprobarMemoria();
      } else if (f === "hecho") {
        ev.preventDefault();
        siguiente();
      }
    }
  }

  // ---------- conexiones ----------

  function conectar() {
    for (const b of document.querySelectorAll("[data-confianza]")) {
      b.addEventListener("click", () => elegirConfianza(Number(b.dataset.confianza)));
    }
    for (const b of document.querySelectorAll("[data-sensacion]")) {
      b.addEventListener("click", () => elegirSensacion(Number(b.dataset.sensacion)));
    }
    $("respuesta").addEventListener("input", alEscribir);
    $("comprobar").addEventListener("click", comprobar);
    $("pista").addEventListener("click", pedirPista);
    $("ver-solucion").addEventListener("click", pedirSolucion);
    $("solucion-si").addEventListener("click", verSolucion);
    $("solucion-no").addEventListener("click", seguirSinSolucion);
    $("no-se").addEventListener("click", noSe);
    $("solo-dos").addEventListener("click", soloDos);
    $("leccion-siguiente").addEventListener("click", leccionSiguiente);
    $("leccion-atras").addEventListener("click", leccionAtras);
    $("leccion-saltar").addEventListener("click", salirDeLeccion);
    $("ver-teoria").addEventListener("click", verTeoria);
    $("modo-examen").addEventListener("click", () => cambiarModo(!modoExamen));
    $("mas-examen").addEventListener("click", () => cambiarModo(true));
    $("vacia-examen").addEventListener("click", () => cambiarModo(true));
    $("reescribir").addEventListener("click", reescribir);
    $("memoria-comprobar").addEventListener("click", comprobarMemoria);
    $("estaba-bien").addEventListener("click", estabaBien);
    $("ver-grafica").addEventListener("click", verGrafica);
    window.addEventListener("resize", ajustarFormulas);
    $("causa-saltar").addEventListener("click", () => {
      if (document.body.dataset.fase === "causa") { $("bloque-causa").hidden = true; registrar(null); }
    });
    $("siguiente").addEventListener("click", siguiente);
    $("ejemplo-comprobar").addEventListener("click", comprobarEjemplo);
    $("ejemplo-seguir").addEventListener("click", seguirTrasEjemplo);
    $("terminar").addEventListener("click", terminar);
    $("salir-final").addEventListener("click", salir);
    $("salir-vacia").addEventListener("click", salir);
    document.addEventListener("keydown", teclado);
    window.addEventListener("error", (ev) => {
      try { api && api.anotar_error(String(ev.message) + " @" + ev.lineno); } catch (_) { /* nada */ }
    });
    document.addEventListener("securitypolicyviolation", (ev) => {
      violaciones.push(ev.violatedDirective + " " + ev.blockedURI);
      try { api && api.anotar_error("CSP: " + ev.violatedDirective + " " + ev.blockedURI); } catch (_) { /* nada */ }
    });
  }

  // Solo para el humo: recorre la leccion abierta, con un fallo y el acierto en cada paso guiado.
  window.leccionCompletaPrueba = () => {
    $("leccion-siguiente").click();
    const ejemplos = $("leccion-cuerpo").querySelectorAll(".ejemplo-leccion").length;
    $("leccion-siguiente").click();
    let pasos = 0, explicaciones = 0;
    while (document.querySelector(".opcion")) {
      const fallo = document.querySelector('.opcion[data-correcta=""]');
      fallo.click();
      explicaciones += document.querySelector(".opcion-nota").dataset.estado === "mal" ? 1 : 0;
      document.querySelector('.opcion[data-correcta="1"]').click();
      $("leccion-siguiente").click();
      pasos += 1;
    }
    const fin = $("leccion-siguiente").textContent;
    $("leccion-siguiente").click();
    return { ejemplos, pasos, explicaciones, fin };
  };

  // Solo para el humo (`practica.py ventana --prueba`), que conduce la interfaz con evaluate_js.
  window.estadoPrueba = () => ({ ficha: actual && actual.ficha, semilla: actual && actual.semilla,
                                 fase: document.body.dataset.fase, violaciones: violaciones.slice() });
  window.escribirPrueba = (texto) => {
    const campo = $("respuesta");
    campo.value = texto;
    campo.dispatchEvent(new Event("input"));
  };

  conectar();
  if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.cola === "function") {
    empezar();
  } else {
    window.addEventListener("pywebviewready", empezar, { once: true });
  }
})();
