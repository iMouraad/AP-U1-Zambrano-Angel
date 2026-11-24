# AP-U1 - Zambrano Yong Angel Daniel

Aplicaciones Distribuidas, séptimo nivel, paralelo B. Examen práctico de la Unidad I: BoletoDistribuido.

## Ejecución

Requiere Python 3.11 o superior, sin bibliotecas externas. Una terminal por oficina:

    python boleto.py nodo 1      # Quevedo, puerto 6001
    python boleto.py nodo 2      # Buena Fe, puerto 6002
    python boleto.py nodo 3      # Valencia, puerto 6003

Vender un asiento desde cualquier oficina: `python boleto.py vender 6001 12`

`boleto.py` es el código del examen. `boleto_corregido.py` es una copia posterior al examen, con `RLock` en lugar de `Lock`.

## Compilación del informe

- Compilador: pdflatex
- Archivo principal: `informe.tex`
- Comandos: `pdflatex informe.tex` dos veces
- Las imágenes están en `evidencia/`. No usa bibliografía.
