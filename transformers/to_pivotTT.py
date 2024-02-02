import re
from pathlib import Path
from typing import List

import xmltodict
from bs4 import BeautifulSoup

from transformers.default import DefaultTransformer
from transformers.enums import Model, Tag
from transformers.utils import File


def elaguer(texte):
    return re.sub(r"\s+", " ", texte).strip()


class PivotTransformerTT(DefaultTransformer):
    def __init__(
            self,
            tags: List[Tag] = None,
            pivot_tags: List[Tag] = None,
            nlp: Model = None,
    ) -> None:
        super().__init__(tags, pivot_tags, nlp)

        self._meta = None

        if self.pivot_tags == set():
            self.pivot_tags = self.tags

        if self.pivot_tags != self.tags:
            raise ValueError("pivot_tags must be equal to tags (or empty) for PivotTransformer")

    def replace_text(self, e: dict | str) -> dict | str | None:
        if isinstance(e, str):
            return self.str_to_pivot(e)

        to_update = {}
        to_remove = []

        for k, v in e.items():
            if isinstance(v, str):
                if "@" not in k:
                    to_update = self.str_to_pivot(v)
                    if k != "#text":
                        to_update = {k: to_update}
                    to_remove.append(k)

            elif isinstance(v, dict):
                e[k] = self.replace_text(v)

            elif isinstance(v, list):
                if v == []:
                    continue
                e[k] = [self.replace_text(x) for x in v if x is not None]

            elif v is None:
                continue

            else:
                raise ValueError

        for k in to_remove:
            del e[k]

        e.update(to_update)
        return e

    def str_to_pivot(self, text: str) -> dict:
        tags = set(self.pivot_tags)

        text = re.sub(r"(\s)+", " ", text)

        doc = self.nlp.tag(text)

        temp_lst = []
        for i, token in enumerate(doc, 1):
            temp = {}
            if Tag("id") in tags:
                temp["@id"] = i
            if Tag("form") in tags:
                temp["@form"] = token[0]
            if Tag("lemma") in tags:
                temp["@lemma"] = token[2]
            if Tag("pos") in tags:
                temp["@pos"] = token[1]

            temp_lst.append(temp)

        return {"w": temp_lst}

    def transform(self, file: File | Path | str) -> dict:
        text = None

        if not isinstance(file, (File, Path, str)):
            raise ValueError(f"file must be a Path, a File or a str ({type(file) = })")

        # name = file.name if "name" in file.__dict__ else file[:10] + "..." + file[-10:]
        # print(f"Processing {name}")

        if isinstance(file, Path):
            with file.open("r", encoding="utf-8") as f:
                text = f.read()

        elif isinstance(file, str):
            text = file

        elif isinstance(file, File):
            text = file.content

        text = re.sub(
            r"(\s)\1+", r"\g<1>", text
        ).strip()  # Dégémination espaces

        text = re.sub(r'<hi rend="\w+">([^<]+)</hi>', r"\g<1>", text)

        self.meta(text)

        text_d = xmltodict.parse(text, attr_prefix="@")

        try:
            text_d["TEI"]["text"] = self.replace_text(text_d["TEI"]["text"])
        except KeyError:
            try:
                text_d["tei"]["text"] = self.replace_text(text_d["tei"]["text"])
            except KeyError:
                text_d = self.replace_text(text_d)

        if self._meta:
            text_d["TEI-EXTRACTED-METADATA"] = self._meta

        return text_d

    def meta(self, file):
        # Might want to use a unique transformer instance on multiple files
        # if self._meta is not None:
        #     return self._meta

        soup = BeautifulSoup(file, "xml")
        self._meta = {}

        TEI = soup.find("TEI")

        if TEI is None:
            TEI = soup.find("tei")

        if TEI is not None:
            teiHeader = TEI.find("teiHeader")
            if teiHeader is None:
                teiHeader = TEI.find("teiheader")

            publicationStmt = teiHeader.find("publicationStmt")
            if publicationStmt is None:
                publicationStmt = teiHeader.find("publicationstmt")

            sourceDesc = teiHeader.find("sourceDesc")
            if sourceDesc is None:
                sourceDesc = teiHeader.find("sourcedesc")

            if sourceDesc is not None:
                sourceDesc = sourceDesc.text

            text = TEI.find("text")

            self._meta = {
                "Titre": teiHeader.find("title").text,
                "Edition": teiHeader.find("edition").text if teiHeader.find("edition") else "N/A",
                "Publication": publicationStmt.find("publisher").text
                if publicationStmt.find("publisher")
                else "N/A",
                "Date": publicationStmt.find("date").attrs["when"]
                if publicationStmt.find("date")
                   and "when" in publicationStmt.find("date").attrs
                else "N/A",
                "Source": elaguer(sourceDesc),
            }
            self._meta = {k: v.strip() for k, v in self._meta.items()}

        else:
            teiHeader = None
            text = soup

        try:
            personnages = text.find("castList").findAll("castItem")
            personnages = [
                {"Id": p.attrs["xml:id"], "Display": elaguer(p.text)}
                if "xml:id" in p.attrs
                else {"Id": "N/A", "Display": p.text}
                for p in personnages
            ]
            self._meta["Personnages"] = personnages
        except AttributeError:
            pass

        try:
            responsables = teiHeader.findAll("respStmt")
            assert responsables is not None
            responsables = [
                {"Name": r.find("name").text, "Role": r.find("resp").text}
                for r in responsables
            ]
            self._meta["Responsables"] = responsables
        except (AttributeError, AssertionError, UnboundLocalError):
            pass

        return self._meta
