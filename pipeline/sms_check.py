"""Verifica codificación y longitud de los copies SMS antes de estimar costos.

GSM-7: 160 caracteres en 1 segmento; 153 por segmento si es concatenado.
Los caracteres de la tabla de extensión ({ } [ ] ~ \\ | ^ €) cuentan doble.
Un solo carácter fuera de GSM-7 (p. ej. á, í, ó, ú, emojis) obliga a UCS-2:
70 caracteres en 1 segmento, 67 por segmento si es concatenado.

    python pipeline/sms_check.py  ->  reports/sms_longitud.csv
"""
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import REPORT_DIR, ROOT  # noqa: E402

GSM_BASICO = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
                 "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM_EXTENSION = set("^{}\\[~]|€")
# Longitud supuesta del enlace corto con seguimiento (p. ej. https://yjg.co/Ab12Cd). Ajustar al acortador real.
LARGO_LINK = 22


def analizar(texto: str):
    texto = texto.replace("{link}", "x" * LARGO_LINK)
    fuera = sorted({ch for ch in texto if ch not in GSM_BASICO and ch not in GSM_EXTENSION})
    if fuera:
        n = len(texto)
        seg = 1 if n <= 70 else math.ceil(n / 67)
        return "UCS-2", n, seg, "".join(fuera)
    n = sum(2 if ch in GSM_EXTENSION else 1 for ch in texto)
    seg = 1 if n <= 160 else math.ceil(n / 153)
    return "GSM-7", n, seg, ""


def main():
    origen = ROOT / "campanas" / "sms_copies.csv"
    salida = REPORT_DIR / "sms_longitud.csv"
    filas = []
    with open(origen, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cod, n, seg, fuera = analizar(r["texto"])
            filas.append({**r, "codificacion": cod, "caracteres_con_link": n, "segmentos": seg,
                          "caracteres_no_gsm": fuera})
            print(f"{r['campana']:6} {r['variante']:10} {cod} {n:4} car. {seg} seg. {fuera}")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with open(salida, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)


if __name__ == "__main__":
    main()
