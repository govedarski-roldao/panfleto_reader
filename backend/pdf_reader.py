import fitz
import os
from ai.ai import extrair_artigos_catalogo
from backend.organize_data import OrganizeData


def remove_img_from_pdf(pdf_path, destination_dir=None,folder_name="extraction"):
    data_frame = OrganizeData()
    if destination_dir:
        base_output_dir = os.path.join(destination_dir, folder_name)
        imgs_dir = os.path.join(base_output_dir, "imgs")
    else:
        parent_dir = os.path.abspath(os.path.join(os.getcwd(), ".."))
        base_output_dir = os.path.join(parent_dir, "result")
        imgs_dir = os.path.join(base_output_dir, "imgs")

    os.makedirs(base_output_dir, exist_ok=True)
    os.makedirs(imgs_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    for page_number in range(len(doc)):
        page = doc.load_page(page_number)
        pix = page.get_pixmap(dpi=300)

        output = os.path.join(imgs_dir, f"pagina_{page_number + 1}.jpg")

        pix.save(output)
        print("Guardado:", output)

        picture_to_analise = extrair_artigos_catalogo(output)
        for item in picture_to_analise["items"]:
            print(item["name"], item["price"])
            data_frame.add_lines(item)

    doc.close()
    print("Todas as folhas do pdf extraidas e convertidas para jpeg")
    data_frame.export_to_excel(base_output_dir)
    print("Ficheiro excel Criado. Nao tens de que Bernardo :)")
    print("Por favor confirma se estao todos os valores correctos. a AI ainda faz alguns erros")


if __name__ == "__main__":
    remove_img_from_pdf(
        r"C:\Users\Utilizador\Desktop\Ideias para negocios\ler_panfletos\backend\Folheto_Digital_Bons_Negcios.pdf"
    )
