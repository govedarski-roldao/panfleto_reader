import fitz

pdf_path = "Folheto_Digital_Bons_Negcios.pdf"

doc = fitz.open(pdf_path)

for page_number in range(len(doc)):
    page = doc.load_page(page_number)

    pix = page.get_pixmap(dpi=300)

    output = f"imgs\pagina_{page_number + 1}.jpg"

    pix.save(output)

    print("Guardado:", output)

doc.close()