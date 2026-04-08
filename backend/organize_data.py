import pandas as pd
import os


class OrganizeData:
    def __init__(self):
        self.df = pd.DataFrame(columns=["Artigo", "Preco"])

    def add_lines(self, line):
        artigo = line["name"]
        preco = line["price"]

        self.df.loc[len(self.df)] = [artigo, preco]
        print("Artigo: ", artigo, " com Preco: ", preco, " adicionado")

    def export_to_excel(self, path):
        os.makedirs(path, exist_ok=True)
        path_total = os.path.join(path, "resultados.xlsx")
        self.df.to_excel(path_total, index=False)
