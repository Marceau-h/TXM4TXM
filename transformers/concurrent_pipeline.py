import json
from copy import deepcopy  # To copy the pivot dict
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import List

import spacy
from treetagger import TreeTagger

from transformers.default import DefaultTransformer
from transformers.enums import Output, MimeType, Tag, Mode, Model
from transformers.epurer import epurer
from transformers.to_conllu import CONLLUTransformer
from transformers.to_hyperbase import HyperbaseTransformer
from transformers.to_pivot import PivotTransformer
from transformers.to_pivotTT import PivotTransformerTT
from transformers.to_xml import XMLTransformer
from transformers.utils import File


# global nlp
# nlp = None


def spacy_load():
    nlp = spacy.load("fr_core_news_sm")
    nlp.max_length = 50000
    return nlp


def treetagger_load(model: Model = Model.french):
    global nlp
    nlp = TreeTagger(
        path_to_treetagger=DefaultTransformer.path_to_treetager(),
        language=model
    )
    return nlp


spacy_nlp = spacy_load()
treetagger_nlp_fr = treetagger_load(Model.french)
treetagger_nlp_old_fr = treetagger_load(Model.old_french)
treetagger_nlp_fr_spoken = treetagger_load(Model.french_spoken)


def pipeline(
        files: List[File],
        output: List[Output] = None,
        tags: List[List[Tag] | Tag] = None,
        mode: Mode = Mode.spacy,
        model: Model = Model.french,
) -> List[File]:
    """Pipeline de transformation des fichiers
    prend une liste de fichiers en entrée et retourne une liste de ces fichiers transformés
    dans les différents formats demandés (xml, json), avec les tags demandés
    (id, form, lemma, pos, text, etc.)
    """

    if output is None:
        output = [Output.json]

    if tags is None:
        tags = [[Tag.id, Tag.form, Tag.lemma, Tag.pos, Tag.text] for _ in output]

    if isinstance(tags[0], Tag):
        tags = [tags for _ in output]

    if len(tags) != len(output):
        if len(tags) == 1:
            tags = [tags[0] for _ in output]

        else:
            raise ValueError("tags must be the same length as files or a single list")

    pivot_tags = list(set([tag for tag_list in tags for tag in tag_list]))

    if mode == Mode.spacy:
        # global nlp
        # spacy_load()
        pass
    elif mode == Mode.treetagger:
        # global nlp
        # treetagger_load(model=model)
        pass
    else:
        raise ValueError("mode must be spacy or treetagger")

    with Pool(cpu_count()) as p:
        """Double esses because lists are in a list when expected result is a simple list
        the starmap is retruning List[List[File]] when the non concurrent version is returning List[File]
        we do this to avoid using threads that would write in the same list and that should have to wait for
        each other to finish writing. This way, each thread writes in its own list and we concatenate them at the end
        to have a single list. Maybe there is a better way to do this, but I don't know it."""

        resultss = p.starmap(
            file_processing,
            [(file, output, tags, pivot_tags, mode, model) for file in files]
        )
        return [result for results in resultss for result in results]


def file_processing(file, output, tags, pivot_tags, mode: Mode = Mode.spacy, model = Model.french) -> List[File]:
    outputs = []
    if not isinstance(file, (File, Path, str)):
        raise ValueError(f"file must be a Path, a File or a str ({type(file) = })")

    # name = file.name if "name" in file.__dict__ else file[:10] + "..." + file[-10:]
    # pbar.set_postfix_str(name)

    match model:
        case Model.french:
            tt_nlp = treetagger_nlp_fr
        case Model.old_french:
            tt_nlp = treetagger_nlp_old_fr
        case Model.french_spoken:
            tt_nlp = treetagger_nlp_fr_spoken



    if file.mime_type == MimeType.xml:
        if mode == Mode.spacy:
            pivot = PivotTransformer(
                tags=pivot_tags, pivot_tags=pivot_tags, nlp=spacy_nlp
            ).transform(file)
        elif mode == Mode.treetagger:
            pivot = PivotTransformerTT(
                tags=pivot_tags, pivot_tags=pivot_tags, nlp=tt_nlp
            ).transform(file)
        else:
            raise ValueError("mode must be spacy or treetagger")
    elif file.mime_type == MimeType.json:
        pivot = file.content
    else:
        raise ValueError("Only xml and pre-pivoted json are supported")

    if Output.pivot in output:
        outputs.append(
            File(
                name=file.with_suffix(".pivot.json"),
                file=json.dumps(pivot, ensure_ascii=False, indent=4),
            )
        )

    if Output.json in output:
        pivot_copy = deepcopy(pivot)
        pivot_copy.pop("TEI-EXTRACTED-METADATA")
        json_str = json.dumps(
            epurer(pivot_copy, tags[output.index(Output.json)]),
            ensure_ascii=False,
            indent=4,
        )
        outputs.append(File(name=file.with_suffix(".json"), file=json_str))

    if Output.txm in output:
        pivot_copy = deepcopy(pivot)
        tag = tags[output.index(Output.txm)] if Output.txm in output else []

        xml = XMLTransformer(tags=tag, pivot_tags=pivot_tags, nlp=nlp).transform(
            pivot_copy
        )

        outputs.append(File(name=file.with_suffix(".xml"), file=xml))

    if Output.conllu in output:
        pivot_copy = deepcopy(pivot)
        tag = tags[output.index(Output.conllu)] if Output.conllu in output else []

        conllu = CONLLUTransformer(tags=tag, pivot_tags=pivot_tags, nlp=nlp).transform(
            pivot_copy
        )

        outputs.append(File(name=file.with_suffix(".conllu"), file=conllu))

    if Output.hyperbase in output:
        pivot_copy = deepcopy(pivot)
        tag = tags[output.index(Output.hyperbase)] if Output.hyperbase in output else []

        hyperbase = HyperbaseTransformer(
            tags=tag, pivot_tags=pivot_tags, nlp=nlp
        ).transform(pivot_copy)

        outputs.append(File(name=file.with_suffix(".hyperbase.txt"), file=hyperbase))

    return outputs
