"""Génère samples/demo_arrets.json.

Les arrêts de ce jeu sont FICTIFS. Ils ne reproduisent que la structure
éditoriale d'une décision de la chambre criminelle (en-tête, visas, exposé du
litige, moyens, motivations, dispositif) afin de faire fonctionner et de tester
l'interface avant toute connexion à l'API. Aucun texte ne cite une
jurisprudence réelle : ne jamais citer ce jeu.

Usage :  python3 tools/make_sample.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crim_hebdo.analysis import build_card  # noqa: E402
from crim_hebdo.config import Config  # noqa: E402


def make_decision(
    decision_id: str,
    number: str,
    date: str,
    solution: str,
    publication: list[str],
    summary: str,
    introduction: str,
    expose: str,
    moyens: str,
    motivations: str,
    dispositif: str,
    visa: list[dict],
    themes_officiels: list[str],
    ecli: str,
    contested: str,
    particular: bool = False,
) -> tuple[dict, dict]:
    """Assemble le texte et calcule les offsets de zones, comme Judilibre."""
    text = ""
    zones: dict[str, list[dict[str, int]]] = {}

    def add(name: str, block: str) -> None:
        nonlocal text
        if not block:
            return
        if text:
            text += "\n\n"
        start = len(text)
        text += block
        zones[name] = [{"start": start, "end": len(text)}]

    add("introduction", introduction)
    add("expose", expose)
    add("moyens", moyens)
    add("motivations", motivations)
    add("dispositif", dispositif)

    short = {
        "id": decision_id,
        "jurisdiction": "cc",
        "chamber": "crim",
        "number": number,
        "numbers": [number],
        "ecli": ecli,
        "formation": "chambre criminelle",
        "publication": publication,
        "decision_date": date,
        "type": "arret",
        "solution": solution,
        "summary": summary,
        "themes": themes_officiels,
        "particularInterest": particular,
    }
    full = {
        "id": decision_id,
        "text": text,
        "zones": zones,
        "visa": visa,
        "partial": False,
        "titlesAndSummaries": [{"title": summary}] if summary else [],
        "contested": {"title": contested, "number": contested.split(",")[0] + ".999", "url": None},
    }
    return short, full


INTRO_HEAD = """Sur le rapport de M. le conseiller rapporteur.

Vu {visas};

La chambre criminelle, vu les articles {articles} du code de procédure pénale,
a lu les moyens urgés par le pourvoi;

La chambre criminelle statuant en formation de la chambre criminelle, a rendu
l'arrêt de la {juridiction} du {date_appel}, qui a produit entre les parties le
dispositif suivant :"""


ARRETS = [
    make_decision(
        "demo0000000000000000000001",
        "25-91.204",
        "2026-09-24",
        "rejet",
        ["b"],
        "Le placement en garde à vue d'une personne majeure sans prolongation "
        "préalable viole l'article 62 du code de procédure pénale.",
        INTRO_HEAD.format(
            visas="les articles 61, 62, 63, 64 et 431 du code de procédure pénale",
            articles="62 et 63",
            juridiction="cour d'appel de Grand-Rivage",
            date_appel="14 mai 2026",
        ),
        "Le 12 février 2026 à 6 heures 20, M. Alpha a fait l'objet d'une "
        "interception sur le domaine public, à la suite d'un signalement. Les "
        "officiers de police judiciaire l'ont conduit au commissariat central à "
        "6 heures 35. Aucune prolongation préalable de son placement en garde à "
        "vue n'a été sollicitée ni obtenue. M. Alpha a été entendu sans la "
        "présence d'un avocat, puis présenté le 13 février 2026 au procureur de la "
        "République, qui a requis la prolongation de sa garde à vue pour "
        "quarante-huit heures additionnelles, mesure autorisée par le président du "
        "tribunal judiciaire.\n\n"
        "Lors de cette audition, M. Alpha a déclaré avoir participé à un "
        "cambriolage et signé deux commandes, ce qu'il a ensuite contesté devant le "
        "juge d'instruction.\n\n"
        "Le 30 avril 2026, la chambre de l'instruction a placé M. Alpha en "
        "détention provisoire et l'a mis en accusation devant la cour d'appel de "
        "Grand-Rivage pour vol avec violence en bande organisée, escroquerie et "
        "faux et usage de faux.",
        "Les moyens soulevés par le pourvoi sont les suivants.\n\n"
        "1°/ le placement en garde à vue de M. Alpha a été effectué sans "
        "prolongation préalable, en violation de l'article 62 du code de "
        "procédure pénale;\n\n"
        "2°/ l'audition de M. Alpha s'est déroulée sans la présence d'un avocat, en "
        "violation de l'article 63-2 du code de procédure pénale;\n\n"
        "3°/ subsidiairement, la cour d'appel a requalifié les faits de tentative de "
        "vol en vol avec violence en se fondant sur des témoignages non recoupés.",
        "Sur la recevabilité du pourvoi et sur le moyen tiré de l'illégalité de la "
        "garde à vue :\n\n"
        "1°/ l'article 62 du code de procédure pénale dispose que, lorsqu'une "
        "personne majeure est interpellée, elle ne peut être retenue que s'il existe "
        "à son encontre des circonstances Objectives graves, constitutives ou non, de "
        "nature à justifier son placement en garde à vue;\n\n"
        "2°/ il résulte de la procédure qu'aucun élément objectif ne justifiait le "
        "placement en garde à vue au moment de l'interpellation;\n\n"
        "3°/ l'absence de prolongation préalable a nécessairement eu une influence "
        "sur la suite de la procédure, puisque les aveux recueillis lors de cette "
        "audition ont été le point de départ des poursuites;\n\n"
        "4°/ en conséquence, il y a lieu à l'évidence de prononcer l'annulation de "
        "la procédure.\n\n"
        "Mais sur le moyen tiré de l'absence d'avocat lors de l'audition :\n\n"
        "5°/ aux termes de l'article 63-2 du code de procédure pénale, la personne "
        "gardée à vue a droit à être assistée d'un avocat lors de ses entretiens, "
        "sauf exception coordonnée;\n\n"
        "6°/ aucune exception n'étant établie, le droit d'assistance a été méconnu.",
        "REJETTE le pourvoi.",
        [
            {"title": "Code de procédure pénale - Article 62", "url": "https://www.legifrance.gouv.fr/"},
            {"title": "Code de procédure pénale - Article 63-2", "url": "https://www.legifrance.gouv.fr/"},
            {"title": "Code de procédure pénale - Article 431", "url": "https://www.legifrance.gouv.fr/"},
        ],
        ["Droit des personnes", "Procédure pénale"],
        "ECLI:FR:CCASS:2026:DEMO01",
        "Cour d'appel de Grand-Rivage, 14 mai 2026",
        particular=True,
    ),
    make_decision(
        "demo0000000000000000000002",
        "25-87.441",
        "2026-09-25",
        "cassation",
        ["b"],
        "Le juge des libertés et de la détention ne peut ordonner le maintien en "
        "détention provisoire sans réexaminer le caractère réel du risque de "
        "récidive.",
        INTRO_HEAD.format(
            visas="les articles 145, 187-1 et 202-1 du code de procédure pénale",
            articles="187-1",
            juridiction="cour d'appel de Grand-Rivage",
            date_appel="2 juin 2026",
        ),
        "M. Bravo, né en 1991, a été mis en examen pour vol avec violence et "
        "extorsion en bande organisée. Le maintien en détention provisoire a été "
        "prononcé le 8 juillet 2026 par le juge des libertés et de la détention, "
        "sans réexamen du risque de récidive ni des considérations relatives à la "
        "personnalité, le juge se bornant à reprendre les motifs de l'ordonnance de "
        "placement.\n\n"
        "Il a saisi le juge d'instruction, puis a interjeté appel devant la chambre "
        "de l'instruction, qui a rejeté sa requête. Condamné à huit ans "
        "d'emprisonnement, il a formé un pourvoi.",
        "Les moyens du pourvoi sont les suivants.\n\n"
        "1°/ le maintien en détention provisoire a été décidé sans réexamen du "
        "risque de récidive ni des considérations de la personnalité;\n\n"
        "2°/ l'ordonnance n'a pas été motivée au regard de l'article 187-1 du code "
        "de procédure pénale;\n\n"
        "3°/ subsidiairement, la peine prononcée est disproportionnée.",
        "Sur les moyens tirés du défaut de réexamen du risque de récidive :\n\n"
        "1°/ aux termes de l'article 187-1 du code de procédure pénale, le juge "
        "des libertés et de la détention statue sur le maintien de la détention "
        "provisoire en tenant compte des éléments de personnalité et en vérifiant "
        "qu'il n'existe aucune raison grave de récidive;\n\n"
        "2°/ il ne peut se borner à reprendre les motifs de la décision de "
        "placement;\n\n"
        "3°/ l'absence de réexamen du risque de récidive vicie le dispositif;\n\n"
        "4°/ l'ordonnance est dépourvue de motivation en ce qu'elle ne répond pas à "
        "l'argument tiré de l'absence de perspective d'insertion ou de réinsertion.\n\n"
        "Mais sur le moyen tiré de la disproportion de la peine :\n\n"
        "5°/ tenant compte de la personnalité du condamné et de sa situation, la "
        "peine de huit ans d'emprisonnement est excédante.",
        "CASSE ET ANNULE, en tous ses dispositions, l'arrêt prononcé par la cour "
        "d'appel de Grand-Rivage le 2 juin 2026, qui viole l'article 187-1 du code "
        "de procédure pénale et n'a pas motivé son maintien en détention "
        "provisoire;\n\n"
        "Renvoie l'affaire au juge des libertés et de la détention de Grand-Rivage, "
        "en l'état.",
        [
            {"title": "Code de procédure pénale - Article 145", "url": "https://www.legifrance.gouv.fr/"},
            {"title": "Code de procédure pénale - Article 187-1", "url": "https://www.legifrance.gouv.fr/"},
        ],
        ["Droit des personnes", "Liberté d'aller et venir", "Procédure pénale"],
        "ECLI:FR:CCASS:2026:DEMO02",
        "Cour d'appel de Grand-Rivage, 2 juin 2026",
        particular=True,
    ),
    make_decision(
        "demo0000000000000000000003",
        "25-74.019",
        "2026-09-23",
        "rejet",
        [],
        "La requalification en association de malfaiteurs voyous requiert une "
        "activité organisée, non résultant de la seule juxtaposition "
        "d'infractions.",
        INTRO_HEAD.format(
            visas="les articles 202-1 et 323-8 du code de procédure pénale",
            articles="202-1",
            juridiction="cour d'appel de Grand-Rivage",
            date_appel="20 avril 2026",
        ),
        "M. Charlie est nommé à l'audience du tribunal correctionnel de Grand-Rivage "
        "d'un procès-verbal pour vol avec violence en bande organisée. La cour "
        "d'appel a requalifié les faits en association de malfaiteurs voyous.\n\n"
        "Pour se rétracter, le condamné soutient que la seule accumulation "
        "d'infractions personnelles ne suffit pas à caractériser un groupement de "
        "personnes ou une entente, faute d'activité coordonnée.",
        "Les moyens du pourvoi sont les suivants.\n\n"
        "1°/ la requalification en association de malfaiteurs voyous est dénuée de "
        "base légale;\n\n"
        "2°/ l'existence d'une entente ou d'un groupement de personnes n'est pas "
        "établie.",
        "Sur le moyen tiré de l'absence de base légale de la requalification :\n\n"
        "1°/ l'article 202-1 du code de procédure pénale n'autorise la "
        "requalification que si les faits chargeant la qualification nouvelle "
        "constituent une infraction différente;\n\n"
        "2°/ la différence substantielle tient à la conformité des faits aux "
        "éléments de l'infraction;\n\n"
        "3°/ l'association de malfaiteurs voyous suppose une activité organisée et "
        "un concert intentionnel dans le temps;\n\n"
        "4°/ la seule juxtaposition d'infractions distinctes commises par les mêmes "
        "personnes ne démontre pas l'existence d'une telle entente;\n\n"
        "5°/ en l'état, la cour d'appel a exactement déduit que les faits établis ne "
        "permettaient pas de caractériser l'infraction retenue, sans qu'il y ait "
        "lieu de lui reprocher une erreur de qualification.\n\n"
        "La requalification opérée doit donc être écartée.",
        "REJETTE le pourvoi.",
        [{"title": "Code de procédure pénale - Article 202-1", "url": "https://www.legifrance.gouv.fr/"}],
        ["Droit pénal", "Responsabilité pénale"],
        "ECLI:FR:CCASS:2026:DEMO03",
        "Cour d'appel de Grand-Rivage, 20 avril 2026",
    ),
    make_decision(
        "demo0000000000000000000004",
        "25-81.765",
        "2026-09-26",
        "rejet",
        ["b"],
        "Le juge d'instruction peut lever le secret médical lorsque la personne "
        "suspectée s'en est expressément excusée, la levée étant alors limitée aux "
        "besoins de l'enquête.",
        INTRO_HEAD.format(
            visas="les articles 77-1 et 100 du code de procédure pénale",
            articles="77-1",
            juridiction="cour d'appel de Grand-Rivage",
            date_appel="6 mai 2026",
        ),
        "M. Delta, médecin, est mis en examen pour atteinte contre la vie sur la "
        "personne d'un patient de son service, dispensé d'un traitement au "
        "bénéfice duquel il est décédé.\n\n"
        "Le juge d'instruction a ordonné, sur réquisition du procureur, la "
        "communication du dossier médical du patient à l'expert. Le médecin "
        "soutient que cette mesure a enfreint le secret médical et le secret des "
        "discussions.",
        "Les moyens du pourvoi sont les suivants.\n\n"
        "1°/ le juge d'instruction a violé le secret médical et le secret des "
        "discussions en communiquant le dossier médical à l'expert;\n\n"
        "2°/ aucune exception n'était prévue par la loi;\n\n"
        "3°/ la mesure a été prise sans l'accord du médecin.",
        "Sur le moyen tiré de la violation du secret médical :\n\n"
        "1°/ aux termes de l'article 77-1 du code de procédure pénale, lorsque la "
        "personne suspectée de complicité s'acquitte de son secret médical, le "
        "juge d'instruction peut ordonner, pour les besoins de l'enquête, que les "
        "dossiers soient communiqués aux médecins amplifiers;\n\n"
        "2°/ la décharge écrite du médecin mentionne expressément son accord pour la "
        "levée du secret médical;\n\n"
        "3°/ la communication a été limitée au seul dossier du patient concerné et "
        "à la durée de l'instruction;\n\n"
        "4°/ dès lors, il n'y a pas lieu de censurer la procédure sur ce chef;\n\n"
        "5°/ c'est au juge d'instruction, seul compétent pour apprécier les cas et "
        "circonstances où les communications sont de droit ou d'opportunité, qu'il "
        "appartient d'ordonner ou non la communication du dossier médical.",
        "REJETTE le pourvoi.",
        [{"title": "Code de procédure pénale - Article 77-1", "url": "https://www.legifrance.gouv.fr/"}],
        ["Santé publique", "Droit des personnes"],
        "ECLI:FR:CCASS:2026:DEMO04",
        "Cour d'appel de Grand-Rivage, 6 mai 2026",
    ),
    make_decision(
        "demo0000000000000000000005",
        "25-69.338",
        "2026-09-22",
        "cassation",
        [],
        "Le délit de revente de stupéfiants est caractérisé dès lors que l'accusé "
        "s'est livré à une revalorisation du produit saisi, sans qu'il soit besoin "
        "d'établir un usage personnel.",
        INTRO_HEAD.format(
            visas="les articles 222-1, L. 628-1 et L. 630-1 du code de la santé publique",
            articles="L. 628-1",
            juridiction="cour d'appel de Grand-Rivage",
            date_appel="12 mars 2026",
        ),
        "Lors de sa garde à vue, M. Echo a déclaré avoir acheté vingt grammes de "
        "cannabis pour cent cinquante euros et avoir procédé à une première "
        "revente pour dix euros. Les policiers ont trouvé dans son véhicule cent "
        "quatre-vingts grammes de produits de cannabis et quatre-vingts euros "
        "en espèces. Il a déclaré que cette quantité était destinée à sa "
        "consommation personnelle.\n\n"
        "La cour d'appel a requalifié les faits de revente en infraction de "
        "revente de stupéfiants et d'usage illicite de stupéfiants, en retenant "
        "que le volume important saisi ne pouvait être expliqué par un usage "
        "personnel.",
        "Les moyens du pourvoi sont les suivants.\n\n"
        "1°/ la revente n'est pas caractérisée, faute de preuve de l'opération de "
        "revente;\n\n"
        "2°/ subsidiairement, l'usage personnel est établi et doit être retenu.",
        "Sur l'élément matériel de la revente :\n\n"
        "1°/ aux termes de l'article L. 628-1 du code de la santé publique, le "
        "délit de revente de stupéfiants est constitué dès lors que l'accusé s'est "
        "livré à une revalorisation du produit stupéfiant saisi;\n\n"
        "2°/ ni le prix d'achat, ni le prix de revente n'ont besoin d'être "
        "déterminés avec certitude;\n\n"
        "3°/ l'existence d'une transaction suffit;\n\n"
        "4°/ la quantité saisie, très supérieure aux besoins d'un usage personnel, "
        "conduise à elle seule dans les circonstances de la cause, à déduire le "
        "caractère habituel et constant du comportement de l'intéressé;\n\n"
        "5°/ il n'y a pas lieu de s'arrêter à l'absence d'usage personnel.\n\n"
        "Mais sur l'absence de qualification d'usage illicite :\n\n"
        "6°/ l'usage illicite de stupéfiants, qui est une infraction clandestine "
        "de danger constant, n'est établi par aucun élément concordant;\n\n"
        "7°/ il doit être renvoyé au juge du fond pour qu'il se prononce sur ce "
        "chef;\n\n"
        "8°/ la cour d'appel a donc tort de s'abstenir et a méconnu l'exigence de "
        "motivation.",
        "CASSE ET ANNULE, en tout ce qu'il a statué sur la qualification d'usage "
        "illicite de stupéfiants, l'arrêt prononcé par la cour d'appel de "
        "Grand-Rivage le 12 mars 2026.",
        [
            {"title": "Code de la santé publique - Article L. 628-1", "url": "https://www.legifrance.gouv.fr/"},
            {"title": "Code pénal - Article 222-1", "url": "https://www.legifrance.gouv.fr/"},
        ],
        ["Santé publique", "Droit pénal"],
        "ECLI:FR:CCASS:2026:DEMO05",
        "Cour d'appel de Grand-Rivage, 12 mars 2026",
    ),
    make_decision(
        "demo0000000000000000000006",
        "25-90.112",
        "2026-09-26",
        "rejet",
        [],
        "L'escroquerie est caractérisée dès lors que la manœuvre dolosive, les "
        "dceptions et le préjudice subséquent sont établis, sans que le mélange de "
        "faits soit pertinent.",
        INTRO_HEAD.format(
            visas="les articles 485 et 495 du code pénal",
            articles="485",
            juridiction="cour d'appel de Grand-Rivage",
            date_appel="1er juillet 2026",
        ),
        "M. Foxtrot est accusé d'escroquerie au préjudice de la société Sigma, à "
        "la suite de factures impayées et d'un rattachement fictif de charges. La "
        "cour d'appel l'a déclaré coupable d'escroquerie pour la seule facture de "
        "quatre-vingt-quatre mille euros contestée.\n\n"
        "Le condamné soutient que les opérations distinctes ont été régularisées et "
        "qu'il a été privé de la possibilité de faire apparaître les compensations "
        "opérées.",
        "Les moyens du pourvoi sont les suivants.\n\n"
        "1°/ les faits retenus se rapportent à des opérations distinctes, dont "
        "certaines ont été régularisées;\n\n"
        "2°/ la cour d'appel a retenu des éléments sans rapport avec la manœuvre "
        "dolosive reprochée;\n\n"
        "3°/ les paiements antérieurs à l'assignation justifiaient l'acquittement.",
        "Sur l'élément intentionnel de l'escroquerie :\n\n"
        "1°/ l'escroquerie suppose une manœuvre dolosive ou des manœuvres "
        "frauduleuses de nature à faire croire à l'existence de faits inexacts ou à "
        "la nonexistence de faits réels;\n\n"
        "2°/ il suffit que la manœuvre, les déceptions et le préjudice subséquent "
        "soient établis;\n\n"
        "3°/ la question du mélange de faits est inopérante dès lors que les "
        "manœuvres frauduleuses retenues sont en relation avec les sommes dont le "
        "versement est contesté;\n\n"
        "4°/ la cour d'appel a exactement déduit que les pièces versées établissaient "
        "la réalité des manœuvres dolosives et l'existence du préjudice;\n\n"
        "5°/ l'appréciation souveraine de la valeur des déclarations et des pièces "
        "n'encadre pas le contrôle de légalité.",
        "REJETTE le pourvoi.",
        [
            {"title": "Code pénal - Article 485", "url": "https://www.legifrance.gouv.fr/"},
            {"title": "Code pénal - Article 495", "url": "https://www.legifrance.gouv.fr/"},
        ],
        ["Droit pénal", "Responsabilité pénale"],
        "ECLI:FR:CCASS:2026:DEMO06",
        "Cour d'appel de Grand-Rivage, 1er juillet 2026",
    ),
]


def main() -> int:
    config = Config(use_llm=False, data_dir=ROOT / "data")
    out = []
    for short, full in ARRETS:
        card = build_card(short, full, config)
        out.append({"meta": card.meta, "analysis": card.analysis, "raw": card.raw})

    payload = {
        "_avertissement": (
            "DONNEES FICTIVES. Ce jeu de demonstration reproduit la structure "
            "editoriale d'arrets de la chambre criminelle mais ne correspond a aucun "
            "arret reel. Ne jamais le citer."
        ),
        "source": "crim_hebdo — jeu de démonstration généré par tools/make_sample.py",
        "arrets": out,
    }
    target = ROOT / "samples" / "demo_arrets.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out)} arrêt(s) de démonstration écrit(s) : {target}")

    for entry in out:
        labels = [t["label"] for t in entry["analysis"]["themes"]]
        flag = "B" if entry["meta"]["au_bulletin"] else " "
        print(f"  [{flag}] {entry['meta']['number']:<12} {labels}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
