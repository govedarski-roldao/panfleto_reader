import cv2
import pytesseract
import pandas as pd
import re
import sys

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def ocr_text(image, psm=6, whitelist=None):
    config = f"--oem 3 --psm {psm}"
    if whitelist:
        config += f' -c tessedit_char_whitelist="{whitelist}"'
    return pytesseract.image_to_string(image, lang="eng", config=config).strip()


def clean_price(text):
    if not text:
        return None

    text = text.replace(" ", "")
    text = text.replace("€", "")
    text = text.replace("¢", "")
    text = text.replace("S", "5")
    text = text.replace("O", "0")

    # tenta formatos normais
    m = re.search(r"(\d{1,2}[.,]\d{2})", text)
    if m:
        return m.group(1).replace(".", ",")

    # tenta formatos tipo 729 -> 7,29
    m = re.search(r"\b(\d{3,4})\b", text)
    if m:
        digits = m.group(1)
        if len(digits) == 3:
            return f"{digits[0]},{digits[1:]}"
        if len(digits) == 4:
            return f"{digits[:-2]},{digits[-2:]}"

    return None


def clean_product_text(text):
    if not text:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = " ".join(lines)

    # remove ruído comum
    noise_patterns = [
        r"\*.*",
        r"preço s/?iva",
        r"mercado da frescura",
        r"excepto.*",
        r"exceto.*",
        r"\bkg\b",
        r"\bunid\b",
        r"\d+[.,]\d{2}",
        r"\b\d+/\d+\b",
    ]

    for pat in noise_patterns:
        joined = re.sub(pat, "", joined, flags=re.IGNORECASE)

    joined = re.sub(r"\s+", " ", joined).strip(" -–—,.;:")
    return joined


def merge_boxes(boxes, y_tol=25):
    """
    Junta caixas muito próximas horizontalmente e na mesma linha.
    """
    if not boxes:
        return []

    boxes = sorted(boxes, key=lambda b: (b[1], b[0]))
    merged = []

    for box in boxes:
        x, y, w, h = box
        placed = False

        for i, (mx, my, mw, mh) in enumerate(merged):
            same_line = abs(y - my) < y_tol
            overlap_or_close = (x <= mx + mw + 30) and (mx <= x + w + 30)

            if same_line and overlap_or_close:
                nx = min(x, mx)
                ny = min(y, my)
                nw = max(x + w, mx + mw) - nx
                nh = max(y + h, my + mh) - ny
                merged[i] = (nx, ny, nw, nh)
                placed = True
                break

        if not placed:
            merged.append(box)

    return merged


def main():
    image_path = "test.png"
    output_excel = "produtos.xlsx"

    img = cv2.imread(image_path)
    if img is None:
        print(f"Não consegui abrir {image_path}")
        sys.exit(1)

    h, w = img.shape[:2]

    # cortar a parte direita onde estão os artigos com preços
    roi = img[:, int(w * 0.54):].copy()

    # aumentar para ajudar OCR
    roi = cv2.resize(roi, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # detetar amarelo das etiquetas de preço
    lower_yellow = (15, 120, 120)
    upper_yellow = (40, 255, 255)
    mask_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)

    # algum fecho morfológico para unir caracteres/zonas partidas
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
    mask_yellow = cv2.morphologyEx(mask_yellow, cv2.MORPH_CLOSE, kernel)
    mask_yellow = cv2.dilate(mask_yellow, kernel, iterations=1)

    contours, _ = cv2.findContours(mask_yellow, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    raw_boxes = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh

        # filtrar caixas pequenas/grandes demais
        if area < 1500:
            continue
        if bw < 60 or bh < 30:
            continue

        raw_boxes.append((x, y, bw, bh))

    price_boxes = merge_boxes(raw_boxes)

    if not price_boxes:
        print("Não encontrei caixas de preço.")
        sys.exit(0)

    results = []
    debug_img = roi.copy()

    for (x, y, bw, bh) in price_boxes:
        # caixa mais apertada do preço
        pad = 8
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(roi.shape[1], x + bw + pad)
        y2 = min(roi.shape[0], y + bh + pad)

        price_crop = roi[y1:y2, x1:x2]

        # preprocess do preço
        gray_price = cv2.cvtColor(price_crop, cv2.COLOR_BGR2GRAY)
        _, thr_price = cv2.threshold(gray_price, 160, 255, cv2.THRESH_BINARY)

        price_text = ocr_text(
            thr_price,
            psm=7,
            whitelist="0123456789,.$€¢"
        )
        price = clean_price(price_text)

        # procurar nome do produto à direita e um pouco acima
        nx1 = min(roi.shape[1], x2 + 5)
        nx2 = min(roi.shape[1], x2 + 260)
        ny1 = max(0, y1 - 40)
        ny2 = min(roi.shape[0], y2 + 50)

        name_crop = roi[ny1:ny2, nx1:nx2]

        gray_name = cv2.cvtColor(name_crop, cv2.COLOR_BGR2GRAY)
        _, thr_name = cv2.threshold(gray_name, 185, 255, cv2.THRESH_BINARY)

        name_text = ocr_text(thr_name, psm=6)
        product = clean_product_text(name_text)

        # fallback: às vezes o nome fica por cima do preço
        if len(product) < 3:
            nx1b = max(0, x1 - 30)
            nx2b = min(roi.shape[1], x2 + 220)
            ny1b = max(0, y1 - 90)
            ny2b = max(0, y1 - 5)

            name_crop2 = roi[ny1b:ny2b, nx1b:nx2b]
            if name_crop2.size > 0:
                gray_name2 = cv2.cvtColor(name_crop2, cv2.COLOR_BGR2GRAY)
                _, thr_name2 = cv2.threshold(gray_name2, 185, 255, cv2.THRESH_BINARY)
                name_text2 = ocr_text(thr_name2, psm=6)
                product2 = clean_product_text(name_text2)
                if len(product2) > len(product):
                    product = product2

        # só guardar resultados minimamente válidos
        if price and product:
            results.append({
                "Produto": product,
                "Preço (€)": price,
                "x": x,
                "y": y
            })

        # debug visual
        cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.rectangle(debug_img, (nx1, ny1), (nx2, ny2), (255, 0, 0), 2)

    if not results:
        print("Foram encontradas caixas de preço, mas não consegui extrair produto/preço válidos.")
        print("Tenta guardar a imagem debug para veres as zonas.")
        cv2.imwrite("debug_boxes.png", debug_img)
        sys.exit(0)

    df = pd.DataFrame(results)
    df = df.sort_values(by=["y", "x"])
    df = df.drop_duplicates(subset=["Produto", "Preço (€)"])
    df = df[["Produto", "Preço (€)"]].reset_index(drop=True)

    print(df)
    df.to_excel(output_excel, index=False)
    cv2.imwrite("debug_boxes.png", debug_img)

    print(f"\nExcel criado: {output_excel}")
    print("Imagem de debug criada: debug_boxes.png")


if __name__ == "__main__":
    main()