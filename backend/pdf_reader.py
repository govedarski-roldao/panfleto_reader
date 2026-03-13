import fitz
import os


def remove_img_from_pdf(pdf_path):
    # Subir um diretório e criar result/imgs
    parent_dir = os.path.abspath(os.path.join(os.getcwd(), ".."))
    result_dir = os.path.join(parent_dir, "result")
    os.makedirs(result_dir, exist_ok=True)
    imgs_dir = os.path.join(result_dir, "imgs")
    os.makedirs(imgs_dir, exist_ok=True)

    # Abrir PDF
    doc = fitz.open(pdf_path)
    for page_number in range(len(doc)):
        page = doc.load_page(page_number)
        pix = page.get_pixmap(dpi=300)

        # Salvar imagem numerada
        output = os.path.join(imgs_dir, f"pagina_{page_number + 1}.jpg")
        pix.save(output)
        print("Guardado:", output)

    doc.close()
remove_img_from_pdf(r"C:\Users\Utilizador\Desktop\Ideias para negocios\ler_panfletos\backend\Folheto_Digital_Bons_Negcios.pdf")