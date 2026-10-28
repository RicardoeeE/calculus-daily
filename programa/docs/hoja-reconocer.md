# Hoja de reconocimiento (antes de calcular)

Lee la integral en voz alta y responde en orden. La primera pregunta con «sí» marca el camino. Si ninguna encaja, reescribe el álgebra (fichas AL-EXP, AL-CUAD y AL-LOG; separa el numerador como en I03) y vuelve a empezar.

1. **¿Está en la tabla tal cual, o tras repartir o separar?** Por ejemplo potencia, e^x, 1/x, sen, cos, 1/(1+x^2). Separa sumas del numerador, nunca del denominador.
2. **¿Es la tabla con (ax+b) dentro?** Entonces es un cambio lineal: se divide entre a.
3. **¿Aparece una función y, multiplicando, su derivada (salvo constante)?** Entonces se sustituye u = esa función. Un caso particular es f'/f, que da ln|f|.
4. **¿Es un producto de un polinomio por e^x, sen, cos, o algo con log o arctan solo?** Entonces es por partes. Se deriva el polinomio, el log o el arctan.
5. **¿Es un cociente de polinomios?**
   - Si el grado de arriba es mayor o igual, primero se divide.
   - Después se factoriza el denominador:
     - con raíces reales salen fracciones simples;
     - con un cuadrático sin raíces, se completa el cuadrado y sale ln + arctan.
6. **¿Hay potencias de sen y cos?**
   - Si una potencia es impar, se aparta un factor y u es la otra función.
   - Si las dos son pares, se usan las fórmulas del ángulo doble.
7. **¿Hay raíces de (ax+b)?** Entonces t^k = ax+b, con k = mcm de los índices.
8. **¿Hay √(a^2 − x^2), √(x^2 + a^2) o √(x^2 − a^2)?** Entonces es un cambio trigonométrico.

**Siempre al terminar:**
- Deriva el resultado y comprueba que sale la función de partida.
- Pon +C.
- Escribe valor absoluto en los ln cuando toque.

**Derivadas parciales:**
- **La otra letra es un número.** Respecto a y, cada x es como un 2. Si cuesta verlo, pon x = 2, deriva y vuelve a poner x.
- **Lo que no lleva la variable.** Si un factor no la lleva, sale fuera multiplicando. Si un sumando no la lleva, vale 0.
- **¿Es exacta?** M va con dx y N con dy. Se calcula ∂M/∂y y ∂N/∂x, en ese orden, y se comparan.

**Para derivar**, las mismas preguntas al revés:
- ¿Es una suma, un producto, un cociente o una composición?
- En una composición, de fuera hacia dentro: cadena.
