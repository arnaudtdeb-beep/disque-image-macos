"""Taxonomie thematique et classifieur pour la chambre criminelle.

Deux niveaux de themes coexistent et sont conserves separement :

1. `themes_officiels` : nomenclature propre de la Cour de cassation, telle que
   fournie par Judilibre (ex. "Droit des personnes", "Vie spirituelle",
   "Santé publique"...). C'est la nomenclature officielle, on ne la modifie pas.
2. `themes` : reperage de pratique, grammatical, construit sur les motifs
   redactionnels reellement employes par la chambre criminelle (nullite,
   detention provisoire, garde a vue...). Ce sont des hypotheses de travail :
   chaque attribution est livree avec les extraits qui la justifient.

Principe : la classification est deterministe, explicable et verifiable.
Un mot cle ne suffit pas a classer : chaque theme exige plusieurs occurrences
significatives, et les faux positifs frequents sont neutralises (`exclude`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .textutil import count_matches, normalize, sentences

# Poids de zone : ce que la chambre ecrit dans ses motivations revele le theme.
ZONE_WEIGHTS = {
    "motivations": 2.2,
    "dispositif": 1.4,
    "moyens": 1.2,
    "expose": 1.0,
    "introduction": 0.8,
    "annexes": 0.5,
}

# Chaque occurrence vaut BASE + le poids de la zone. Le BASE évite qu'un thème
# ne dépende du seul nombre de répétitions d'un terme dans une même zone.
BASE_WEIGHT = 2.5

# Un même motif ne peut peser que trois fois : la répétition d'une formule
# usuelle (détention provisoire, compétence…) ne doit pas écraser les autres
# thèmes réellement traités.
MAX_HITS_PER_PATTERN = 3

MIN_SCORE = 7.0
MIN_MATCHES = 2
MAX_THEMES = 5
FALLBACK_THEME = ("procedure_criminale", "Procédure criminelle (non spécialisé)", "🗂️")


@dataclass(frozen=True)
class Theme:
    code: str
    label: str
    icon: str
    patterns: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    note: str = ""


THEMES: tuple[Theme, ...] = (
    Theme(
        code="nullite",
        label="Nullité",
        icon="⛔",
        patterns=(
            r"\bnullit[ée]s?\b",
            r"\bmoyens? de nullit[ée]\b",
            r"nullit[ée] (?:du|de la|des) ",
            r"\bic[eé]\s+ce qu'il y a lieu de (?:prononcer|constater)",
            r"\bviolation (?:des dispositions de l['’]article|du formalisme|de la loi)",
            r"\bill[ée]galit[ée]s?\b",
            r"\bannul(?:ation|er|é)e?s?\b.{0,60}\b(?:jugement|arr[êe]t|acte|proc[ée]dure)",
            r"(?:prononcer|retenir|constater) l['’]annulation",
            r"\bordre public\b",
            r"\bvices? de la proc[ée]dure\b",
            r"\bformes? substantielles\b",
            r"\bomis(?:e|sion)\s+(?:de\s+formes?|des\s+formes?)\b",
        ),
        keywords=("nullité", "nullite"),
        note="Nullité de l'acte, de la procédure ou du jugement ; moyen soulevé ou retenu par la Cour.",
    ),
    Theme(
        code="controle_legality",
        label="Contrôle de légalité des actes",
        icon="🔎",
        patterns=(
            r"contr[oô]le de la l[ée]galit[ée]",
            r"irr[ée]gularit[ée] (?:substantielle|de forme|de l['’]acte|de la proc[ée]dure)",
            r"actes? d['’]enqu[êe]te",
            r"requalification de l['’]acte",
            r"r[ée]gularit[ée] des (?:actes|poursuites|investigations)",
        ),
        keywords=("contrôle de légalité",),
        note="Régularité formelle ou substantielle des actes d'enquête, moyen de l'ordre public.",
    ),
    Theme(
        code="detention_provisoire",
        label="Détention provisoire",
        icon="🔒",
        patterns=(
            r"d[ée]tention provisoire",
            r"\bplacement en d[ée]tention\b",
            r"\bmaintien (?:de la |en )d[ée]tention\b",
            r"\bprolongation (?:de la |d['’]une? )d[ée]tention\b",
            r"\bcontr[oô]le (?:de la l[ée]galit[ée] de la )d[ée]tention\b",
            r"\bbracelet (?:[ée]lectronique|num[ée]rique)\b",
            r"\bassignation \u00e0 r[ée]sidence\b",
        ),
        keywords=("détention provisoire",),
        note="Placement, maintien, prolongation, contrôle de la légalité ou Quantum de la détention provisoire.",
    ),
    Theme(
        code="garde_a_vue",
        label="Garde à vue",
        icon="⏱",
        patterns=(
            r"\bgarde \u00e0 vue\b",
            r"\bprolongation (?:exceptionnelle )?de la garde \u00e0 vue\b",
            r"\bplacement en garde \u00e0 vue\b",
            r"dur[ée]e (?:de la |de l['’])garde \u00e0 vue",
        ),
        keywords=("garde à vue",),
        note="Durée, conditions et régularité de la garde à vue.",
    ),
    Theme(
        code="audition_enquete",
        label="Audition libre et enquête",
        icon="🎙",
        patterns=(
            r"\baudition libre\b",
            r"\benqu[êe]tes?\s+(?:pr[ée]liminaire|pr[ée]alable|polic[iì]re)\b",
            r"\bactes? d'enqu[êe]te\b",
            r"\bconvocation[s]?\b",
            r"\bextrait[s]? de l['’]enqu[êe]te\b",
            r"\bexamen d['’]enqu[êe]te[s]?\b",
            r"\bacte[s]? d['’]instruction\b",
            r"\br[ée]quisitoire\b",
            r"\bmesures? de surveillance\b",
        ),
        keywords=("audition libre",),
        note="Auditions, convocations, nature et conditions des actes d'enquête.",
    ),
    Theme(
        code="droits_defense",
        label="Droits de la défense",
        icon="⚖️",
        patterns=(
            r"droits? de la d[ée]fense",
            r"droit \u00e0 un proc[èe]s \u00e9quitable",
            r"\bpr[ée]somption d['’]innocence\b",
            r"\baccus[ée]e? (?:de la |du )d[ée]fense\b",
            r"avocat (?:choisi|d[ée]sign[ée]|pr[ée]sent)",
            r"(?:pr[ée]sence|absence) d['’]un avocat",
            r"droit (?:d['’]|à l['’])assistance",
            r"\bassist[ée] d['’]un avocat\b",
            r"d[ée]fense de l['’]accus[ée]",
            r"communication (?:du dossier|des pi[èe]ces)",
            r"\bconsultation du dossier\b",
        ),
        exclude=(r"avocat g[ée]n[ée]ral",),
        keywords=("droits de la défense",),
        note="Intervention du conseil, assistance, communication des pièces, garanties de l'équité du procès.",
    ),
    Theme(
        code="duree_procedure",
        label="Durée de la procédure",
        icon="⏳",
        patterns=(
            r"dur[ée]e (?:raisonnable|du proc[èe]dures?|de l'instruction)",
            r"\bd[ée]lai raisonnable\b",
            r"\bdiligence\b",
            r"\bprolongation (?:de l['’]instruction|exceptionnelle de l['’]instruction)\b",
            r"\binstruction (?:est|devait|devrait) (?:close|clôtur[ée]e)",
        ),
        keywords=("durée de la procédure",),
        note="Caractère diligent de la procédure, délai raisonnable, clôture tardive de l'instruction.",
    ),
    Theme(
        code="qualification",
        label="Qualification de l'infraction",
        icon="🏷",
        patterns=(
            r"\bqualifications?\b",
            r"\bqualification (?:p[ée]nale|juridique|de l['’]infraction)",
            r"\brequalifi(?:ée|cation|er)\b",
            r"\b[ée]l[ée]ments? (?:constitutifs?|mat[ée]riels?|intentionnels?)\b",
            r"\b(?:contient|constitue) (?:l['’]infraction|un d[ée]lit)",
        ),
        keywords=("qualification",),
        note="Choix de la qualification juridique, discussion des éléments constitutifs.",
    ),
    Theme(
        code="preuve",
        label="Preuve, expertise, aveu",
        icon="🔬",
        patterns=(
            r"\bexpert(?:ise| ise)?\b",
            r"\bexpertise\b",
            r"\baveu(?:x)?\b",
            r"\bpr[èe]l[èe]vement(?:s)? (?:biologique|ADN)\b",
            r"\bADN\b",
            r"\btrace(?:s)? (?:num[ée]rique|balistique)\b",
            r"\bmode op[ée]ratoire\b",
        ),
        exclude=(r"avocat g[ée]n[ée]ral",),
        keywords=("expertise",),
        note="Valeur probante des expertises, de l'aveu, des traces et techniques de recherche.",
    ),
    Theme(
        code="perquisition",
        label="Perquisition et saisie",
        icon="🔦",
        patterns=(
            r"\bperquisition\b",
            r"\bvisite domiciliaire\b",
            r"\bdomicile\b.{0,60}\bvisit[ée]",
            r"\bsaisie\b",
            r"ouverture des portes",
            r"\bmandat (?:de recherche|d['’]arrestation|arr[êe]t)\b",
        ),
        keywords=("perquisition",),
        note="Régularité de la perquisition, de la visite domiciliaire et des saisies.",
    ),
    Theme(
        code="voies_recours",
        label="Voies de recours",
        icon="📐",
        patterns=(
            r"\bvoies? de recours\b",
            r"\bd[ée]claration d['’]appel\b",
            r"\bexamen de la recevabilit[ée]\b",
            r"\brecevabilit[ée]\b",
            r"\bcl[ée]ment (?:de l['’]appel|du pourvoi)\b",
            r"\bpourvoi (?:est|doit) (?:rejet[ée]|rejeter)\b",
        ),
        keywords=("voie de recours",),
        note="Recevabilité et régularité de la voie de recours choisie par l'appelant.",
    ),
    Theme(
        code="competence",
        label="Compétence",
        icon="🗺️",
        patterns=(
            r"\bcomp[ée]tence\b",
            r"\bincomp[ée]tence\b",
            r"juridiction (?:d['’]exception|de droit commun)",
            r"\battribution\b.{0,30}\bcomp[ée]tence\b",
        ),
        keywords=("compétence",),
        note="Répartition des compétences entre juridictions.",
    ),
    Theme(
        code="peines",
        label="Peines et sanctions",
        icon="⚖",
        patterns=(
            r"\bpeine privative de libert[ée]\b",
            r"\bpeines? (?:compl[ée]mentaires|diverses|corr[ée]latives|prononc[ée]e?s?)\b",
            r"\br[ée]clusion\b",
            r"\batt[ée]nuation (?:de la peine|de la sanction)\b",
            r"\baggravation de la peine\b",
            r"\bquantum\b",
            r"\bmise en [ée]chelon\b",
        ),
        keywords=("peine",),
        note="Choix et quantum de la peine, modalités de la sanction.",
    ),
    Theme(
        code="sursis",
        label="Sursis avec mise à l'épreuve",
        icon="🕊",
        patterns=(
            r"\bsursis \u00e0 l['’][ée]preuve\b",
            r"\bsursis avec mise \u00e0 l['’][ée]preuve\b",
            r"\bmesure de sursis\b",
            r"\bp[ée]riode probatoire\b",
            r"\bprobation\b",
        ),
        keywords=("sursis à l'épreuve",),
        note="Sursis probatoire : périodicité, manquements, révocation.",
    ),
    Theme(
        code="execution_peine",
        label="Exécution de la peine",
        icon="🏢",
        patterns=(
            r"\bex[ée]cution de la peine\b",
            r"\bsursis \u00e0 l['’]ex[ée]cution\b",
            r"\bplacement sous surveillance\b",
            r"\br[ée]gime de d[ée]tention\b",
            r"\bmaison d['’]arr[êe]t\b",
            r"\bam[ée]nagement de peine\b",
            r"\bp[ée]riode de s[ûu]ret[ée]\b",
            r"\btravail d['’]int[êe]r[êe]t g[ée]n[ée]ral\b",
            r"\bcentres? de probation\b",
        ),
        keywords=("exécution de la peine",),
        note="Modalités d'exécution de la peine, aménagement, TIG, périodes de sûreté.",
    ),
    Theme(
        code="recidive",
        label="Récidive",
        icon="🔁",
        patterns=(
            r"\br[ée]cidive\b",
            r"[ée]tat de r[ée]cidive",
            r"\bcasier judiciaire\b",
            r"\bpropositions? de gr[âa]ce\b",
        ),
        keywords=("récidive",),
        note="État de récidive, antériorités, propositions de grâce.",
    ),
    Theme(
        code="stupefiants",
        label="Stupéfiants",
        icon="💊",
        patterns=(
            r"\bstup[ée]fiants?\b",
            r"\bcannabis\b",
            r"\bcoca[ïi]ne\b",
            r"\bm[ée]thadone\b",
            r"\btraitement de substitution\b",
            r"\btoxicomanie\b",
        ),
        keywords=("stupéfiants",),
        note="Infractions stupéfiants, substitution, toxicomanie.",
    ),
    Theme(
        code="mineurs",
        label="Mineurs",
        icon="🧒",
        patterns=(
            r"\bmineurs?\b",
            r"\bd[ée]linquant(?:e)? juv[ée]nil(?:e)?\b",
            r"\bmajeur (?:[ée]mancip[ée]|âg[ée])\b",
            r"\bjuridiction pour mineurs\b",
            r"\bservice [ée]ducatif\b",
        ),
        keywords=("mineurs",),
        note="Responsabilité des mineurs, mesures de protection.",
    ),
    Theme(
        code="victime",
        label="Statut de la victime",
        icon="🕯",
        patterns=(
            r"\bconstitution de partie civile\b",
            r"\bvictimes?\b",
            r"\bdommages?[- ]int[ée]r[êe]ts\b",
            r"\bindemnisation\b",
            r"\br[ée]paration (?:du pr[ée]judice|int[ée]grale)\b",
            r"\baction ([aà] titre de dommages)\b",
        ),
        keywords=("victime",),
        note="Partie civile, préjudice, réparation.",
    ),
    Theme(
        code="immigration",
        label="Étranger et éloignement",
        icon="🛂",
        patterns=(
            r"\b[ée]trangers?\b",
            r"\bmesure d['’][ée]loignement\b",
            r"\bex[ée]cution (?:de la mesure|prioritaire)\b",
            r"\bexpulsion\b",
            r"\btitre de s[ée]jour\b",
            r"\brequ[êe]rant(?:e)? asympt[ée]\b",
        ),
        keywords=("éloignement",),
        note="Droit des étrangers, exécution des mesures d'éloignement.",
    ),
    Theme(
        code="escroquerie",
        label="Escroquerie et fraude",
        icon="💰",
        patterns=(
            r"\bescroquerie\b",
            r"\bfraude\b",
            r"\busages frauduleux\b",
            r"\babus de confiance\b",
            r"\bd[ét]ournement\b",
            r"\bfaux (?:et usage de faux|billet|num[ée]ro)\b",
            r"\bblanchiment\b",
        ),
        keywords=("escroquerie",),
        note="Escroquerie, abus de confiance, détournement, faux, blanchiment.",
    ),
    Theme(
        code="cybersecurite",
        label="Cybercriminalité et numérique",
        icon="💻",
        patterns=(
            r"\binformatique\b",
            r"\bnum[ée]rique\b",
            r"\bdonn[ée]es personnelles\b",
            r"\br[ée]seau(?:x)? social(?:aux)?\b",
            r"\bsite internet\b",
            r"\bharc[èe]lement\b",
        ),
        keywords=("informatique",),
        note="Infractions dématérialisées, données personnelles, réseaux sociaux.",
    ),
    Theme(
        code="corruption",
        label="Corruption et intégrité publique",
        icon="🏛",
        patterns=(
            r"\bcorruption\b",
            r"\btrafic d['’]influence\b",
            r"\bprise ill[ée]gale d['’]int[ée]r[êe]ts\b",
            r"\bdétournement (?:de fonds|de deniers publics)\b",
            r"\bmarch[ée]s? public",
            r"\bfonctionnaire public\b",
        ),
        keywords=("corruption",),
        note="Atteintes à la probité, corruption, trafic d'influence, marchés publics.",
    ),
    Theme(
        code="qpc",
        label="Question prioritaire de constitutionnalité",
        icon="⚖",
        patterns=(
            r"questions?\s+prioritaires?\s+de\s+constitutionnalit[ée]",
            r"\bQPCs?\b",
            r"questions?\s+constitutionnelles?",
            r"\bnon-conformit[ée]\b.{0,40}\bconstitution\b",
            r"\brenvoi(?:e|er)?\s+au\s+Conseil\s+constitutionnel\b",
        ),
        keywords=("QPC",),
        note="QPC tranchée ou renvoyée au Conseil constitutionnel.",
    ),
    Theme(
        code="sante",
        label="Santé publique et médecine",
        icon="🩺",
        patterns=(
            r"\bincapacit[ée] totale de travail\b",
            r"\bITT\b",
            r"\bconsolidation\b",
            r"\bvictimation\b",
            r"\b(?:agressions? physiques?|violences?) volontaires\b",
            r"\bvictime\b.{0,30}\bbless[ée]",
            r"\bsecret m[ée]dical\b",
            r"\bviolation du secret\b",
            r"\bpr[ée]vention sanitaire\b",
        ),
        keywords=("incapacité totale de travail",),
        note="ITT, victimation, blessures, secret médical, santé publique.",
    ),
    # ------------------------------------------------------------------
    # Thèmes ajoutés après examen des sommaires officiels de la Cour
    # (open data DILA) : la chambre criminelle traite aussi ces matières.
    Theme(
        code="droits_fondamentaux",
        label="Droits fondamentaux (Convention européenne)",
        icon="🕊",
        patterns=(
            r"convention de sauvegarde des droits de l'homme",
            r"article\s+(?:5|6|7|8|10|13|18)\s+de\s+la\s+convention",
            r"\bviolation\b.{0,60}\bconvention\b",
            r"\barticle\s+6\s*\bd.{+}",
            r"\. \d+\s?§\s?\d+.{0,40}\bconvention\b",
            r"\bexécration|\btorture|\btraitement inhumain",
        ),
        keywords=("Convention de sauvegarde des droits de l'homme",),
        note="Articles 5, 6, 8, 10 de la CEDH, durée de la procédure, secret des correspondances.",
    ),
    Theme(
        code="presse",
        label="Liberté d'expression et de la presse",
        icon="📰",
        patterns=(
            r"\bdroit\s+(?:de\s+r[ée]ponse|à\s+l'information)\b",
            r"\bpresse\b",
            r"\bdiffamation\b",
            r"\binjures?\b",
            r"\bdroit de la presse\b",
            r"\barticle\s+10\s+de\s+la\s+convention\b",
        ),
        keywords=("presse", "diffamation"),
        note="Diffamation, injures, droit de réponse, articles de presse.",
    ),
    Theme(
        code="vie_privee",
        label="Vie privée et correspondances",
        icon="🔒",
        patterns=(
            r"\bvie\s+priv[ée]e\b",
            r"\bsecret\s+des\s+correspondances\b",
            r"\beatteinte\s+[àa]\s+la\s+vie\s+priv[ée]e\b",
            r"\bsurveillance\b.{0,40}\btéléphone\b|\btéléphone\b.{0,40}\bsurveillance\b",
            r"\bcaptation\b.{0,30}\bconversation\b|\benregistrement\b.{0,30}\bconversation\b",
            r"\broom\s+[àa]\s+local\b",
        ),
        keywords=("vie privée",),
        note="Vie privée, secret des correspondances, perquisitions de domiciles.",
    ),
    Theme(
        code="douanes",
        label="Douanes et droits indirects",
        icon="🛃",
        patterns=(
            r"\bdouane[s]?\b",
            r"\bcode des douanes\b",
            r"\bdroits?\s+(?:indirects?|de\s+douane)\b",
            r"\bcontrole\s+(?:douanier|frontalier)\b",
            r"\bretenue\s+douani[èe]re\b",
            r"\bvisite\s+(?:imm[ée]diatе|de\s+contresente)\b",
        ),
        keywords=("douanes",),
        note="Fraude aux droits de douane, contrôle frontalier, retenue douanière, visite.",
    ),
    Theme(
        code="environnement",
        label="Environnement et écologie",
        icon="🌿",
        patterns=(
            r"\bprotection\s+de\s+la\s+nature\b",
            r"\bnuisances?\s+sonores?\b",
            r"\bcode\s+de\s+l'environnement\b",
            r"\bpr[ée]jugement\s+environnemental\b",
            r"\br[ée]f[ée]r[ée]\s+environnemental",
            r"\bbr[ûu]l[ée]s?\s+(?:de\s+v[ée]hicules?|d['’]ordures?)\b",
        ),
        keywords=("environnement",),
        note="Référé environnemental, pollutions, ARTICLE 40-1 et suivants.",
    ),
    Theme(
        code="urbanisme",
        label="Urbanisme et permis de construire",
        icon="🏗",
        patterns=(
            r"\bcode\s+de\s+l'urbanisme\b",
            r"\bpermis\s+de\s+construire\b",
            r"\bplan\s+d'occupation\s+des\s+sols\b",
            r"\bd[ée]claration\s+pr[ée]alable\s+de\s+travaux\b",
            r"\bL\.\s*480-7\b",
            r"\bordre\s+de\s+d[ée]molition\b",
        ),
        keywords=("urbanisme",),
        note="Permis de construire, déclaration préalable, demolition, affichage.",
    ),
    Theme(
        code="circulation",
        label="Circulation routière",
        icon="🚗",
        patterns=(
            r"\bcode\s+de\s+la\s+route\b",
            r"\baccident\s+corporel\b",
            r"\bconducteur\b.{0,40}\bpermis\s+de\s+conduire\b",
            r"\bpermis\s+de\s+conduire\b",
            r"\bconducteur\s+d[ée]cev[ée]\b|\balcool[ée]\b.{0,20}\bconduite\b",
            r"\bexc[ée]dition?\s+de\s+vitesse\b|\bradare\b",
        ),
        keywords=("code de la route",),
        note="Accidents corporels, conduite sous influence, sanctions administratives.",
    ),
    Theme(
        code="code_special",
        label="Infractions aux codes spéciaux (chasse, pêche, enzymes)",
        icon="🌲",
        patterns=(
            r"\bplan\s+de\s+chasse\b|\bchasse\b.{0,30}\bcontravention\b",
            r"\bp[êe]che\b",
            r"\bdrogu[ée]s?\b|\bproduits\s+stup[ée]fiants?\b",
            r"\bsanté\s+animale\b|\benzo[ée]\b",
            r"\benregistrement\s+de\s+donn[ée]es\b|\bfichier\s+criminel\b",
        ),
        keywords=("chasse", "pêche"),
        note="Chasse, pêche, animaux, stupéfiants, fichiers criminels.",
    ),
    Theme(
        code="loi_dans_le_temps",
        label="Application de la loi dans le temps",
        icon="⏱",
        patterns=(
            r"\bloi\s+(?:de\s+forme\s+et\s+de\s+proc[ée]dure|imm[ée]diatement\s+applicable)\b",
            r"\bapplication\s+(?:imm[ée]diate|dans\s+le\s+temps)\b",
            r"\br[ée]troactivit[ée]\b",
            r"\bloi\s+plus\s+favorable\b",
            r"\bcriminalit[ée]\s+de\s+la\s+s[ée]curit[ée]e?\b.{0,40}\bloi\b",
        ),
        keywords=("application immédiate",),
        note="Loi de forme et de procédure, rétroactivité, loi plus favorable.",
    ),
    Theme(
        code="indemnisation",
        label="Restitution et indemnisation",
        icon="💶",
        patterns=(
            r"\brestitution\b",
            r"\bindemnisation\b",
            r"\br[ée]paration\s+int[ée]grale\b",
            r"\bpr[ée]judice\s+sexuel\b",
            r"\br[ée]paration\s+du\s+pr[ée]judice\b",
            r"\bpr[ée]judice\s+(?:moral|mat[ée]riel)\b",
        ),
        keywords=("restitution",),
        note="Restitution, réparation intégrale, préjudice moral et matériel.",
    ),
    Theme(
        code="juridiction",
        label="Composition et attributions de la juridiction",
        icon="🏛",
        patterns=(
            r"\bcomposition\s+de\s+la\s+juridiction\b",
            r"\bmembres\s+de\s+la\s+(?:juridiction|cour)\b",
            r"\bmentions\s+obligatoires\b",
            r"\bpr[ée]sident\b.{0,40}\bgreffier\b",
            r"\btribunal\s+de\s+grande\s+instance\b.{0,40}\bcomposition\b",
            r"\bconseiller\b.{0,30}\bgreffier\b",
        ),
        keywords=("composition de la juridiction",),
        note="Mentions obligatoires, composition, irrégularités de jugement et d'arrêt.",
    ),
)

THEME_INDEX: dict[str, Theme] = {theme.code: theme for theme in THEMES}

@dataclass
class ClassifiedTheme:
    code: str
    label: str
    icon: str
    score: float
    confidence: float
    matches: int
    evidence: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "icon": self.icon,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
            "matches": self.matches,
            "evidence": self.evidence,
            "note": self.note,
        }


def classify(
    zones: dict[str, str],
    full_text: str = "",
    top: int = MAX_THEMES,
    official_matters: list[str] | tuple[str, ...] | None = None,
) -> list[ClassifiedTheme]:
    """Classe un arrêt et renvoie les thèmes retenus, justifie par des extraits.

    `official_matters` contient les matières du sommaire de la Cour (source DILA).
    Elles complètent la détection par le texte : une matière officielle designation
    peut retenir son thème même quand les motifs ne franchissent pas le seuil.
    """
    results: list[ClassifiedTheme] = []
    for theme in THEMES:
        score = 0.0
        matches = 0
        evidence: list[str] = []

        for zone, zone_text in zones.items():
            if not zone_text:
                continue
            weight = ZONE_WEIGHTS.get(zone, 1.0)
            for pattern in theme.patterns:
                hits = count_matches(zone_text, pattern)
                if not hits:
                    continue
                if any(count_matches(zone_text, exclusion) for exclusion in theme.exclude):
                    hits = 0
                    continue
                score += min(hits, MAX_HITS_PER_PATTERN) * (BASE_WEIGHT + weight)
                matches += hits

        if matches < MIN_MATCHES or score < MIN_SCORE:
            continue

        evidence = _evidence_for(theme, zones)
        results.append(
            ClassifiedTheme(
                code=theme.code,
                label=theme.label,
                icon=theme.icon,
                score=score,
                confidence=min(1.0, score / 40.0),
                matches=matches,
                evidence=evidence,
                note=theme.note,
            )
        )

    results.sort(key=lambda t: t.score, reverse=True)

    # Thèmes induits par la nomenclature officielle de la Cour, s'ils ne sont pas
    # déjà retenus par le texte. Le score est indicatif et inférieur à celui d'un
    # thème démontré par les motifs.
    for code in theme_codes_for_official(official_matters):
        if any(r.code == code for r in results):
            continue
        theme = THEME_INDEX[code]
        results.append(
            ClassifiedTheme(
                code=code,
                label=theme.label,
                icon=theme.icon,
                score=0.0,
                confidence=0.0,
                matches=0,
                evidence=[],
                note=f"Matière officielle de la Cour : {', '.join(m for m in (official_matters or []) if OFFICIAL_TO_THEME.get(str(m).strip()) == code)}.",
            )
        )

    selected = results[:top]
    if not selected:
        selected = [
            ClassifiedTheme(
                code=FALLBACK_THEME[0],
                label=FALLBACK_THEME[1],
                icon=FALLBACK_THEME[2],
                score=0.0,
                confidence=0.0,
                matches=0,
                evidence=[],
                note="Aucun thème spécialisé atteint le seuil de détection ; classement générique, à qualifier manuellement.",
            )
        ]
    return selected


# ---------------------------------------------------------------------------
# Rattachement de la nomenclature officielle de la Cour à la taxonomie.
#
# Le sommaire de la Cour est un indice fort et objectively vérifiable : quand il
# désigne une matière (PEINES, DOUANES, URBANISME…), on s'appuie dessus pour
# retenir le thème correspondant même si les motifs du texte ne suffisent pas à
# franchir le seuil de détection. Le rattachement est explicite, donc auditable.
# ---------------------------------------------------------------------------
# Les matières génériques de la Cour (ACTION PUBLIQUE, CASSATION, PRESCRIPTION)
# sont volontairement absentes : elles ne désignent aucune matière de fond et ne
# doivent donc pas déclencher de thème.
OFFICIAL_TO_THEME: dict[str, str] = {
    "ACTION CIVILE": "indemnisation",
    "APPEL CORRECTIONNEL": "voies_recours",
    "APPEL CORRECTIONNEL OU DE POLICE": "voies_recours",
    "ABUS DE CONFIANCE": "escroquerie",
    "ACCIDENT DE LA CIRCULATION": "circulation",
    "ATTEINTE A LA VIE PRIVEE": "vie_privee",
    "ATTEINTE A L'AUTORITE DE L'ETAT": "corruption",
    "ATTEINTE A L'INTEGRITE PHYSIQUE OU PSYCHIQUE DE LA PERSONNE": "sante",
    "AUDIT": "corruption",
    "BLANCHIMENT": "escroquerie",
    "BOURSE": "escroquerie",
    "CHAMBRE DE L'INSTRUCTION": "audition_enquete",
    "CHASSE": "code_special",
    "CIRCULATION ROUTIERE": "circulation",
    "CONFIDENCE": "escroquerie",
    "CONVENTION DE SAUVEGARDE DES DROITS DE L'HOMME ET DES LIBERTES FONDAMENTALES": "droits_fondamentaux",
    "CONVENTIONS INTERNATIONALES": "droits_fondamentaux",
    "CONFISCATION": "peines",
    "CONTREFAÇON": "qualification",
    "COUR D'ASSISES": "competence",
    "CRIMES ET DELITS FLAGRANTS": "audition_enquete",
    "CRIMINALITE ORGANISEE": "escroquerie",
    "CUMUL IDEAL D'INFRACTIONS": "qualification",
    "DETENTION PROVISOIRE": "detention_provisoire",
    "DETOURNEMENT D'OBJETS SAISIS OU REMIS EN GAGE": "perquisition",
    "DONNÉES DE CONNEXION": "cybersecurite",
    "DROITS DE LA DEFENSE": "droits_defense",
    "DOUANES": "douanes",
    "ECOTASSE": "environnement",
    "ENLEVEMENT ET SEQUESTRATION": "sante",
    "ENQUETE": "audition_enquete",
    "ENQUETE PRELIMINAIRE": "audition_enquete",
    "ESCROQUERIE": "escroquerie",
    "EXPERTISE": "preuve",
    "FICHIERS ET LIBERTES PUBLIQUES": "vie_privee",
    "FICHIER NATIONAL AUTOMATISE DES EMPREINTES GENETIQUES (FNAEG)": "vie_privee",
    "FRAUDES ET FALSIFICATIONS": "escroquerie",
    "GARDE A VUE": "garde_a_vue",
    "GEOLOCALISATION": "cybersecurite",
    "INFORMATIQUE": "cybersecurite",
    "INJURES": "presse",
    "INSTRUCTION": "audition_enquete",
    "JUGEMENTS ET ARRETS": "juridiction",
    "JURIDICTIONS CORRECTIONNELLES": "competence",
    "JURIDICTIONS DE L'APPLICATION DES PEINES": "execution_peine",
    "LIBERATION CONDITIONNELLE": "execution_peine",
    "MANDAT D'ARRET EUROPEEN": "droits_fondamentaux",
    "MISE EN DANGER DE LA PERSONNE": "sante",
    "MINEUR": "mineurs",
    "PEINES": "peines",
    "PRISON": "peines",
    "PRESSE": "presse",
    "PROTECTION DE LA NATURE ET DE L'ENVIRONNEMENT": "environnement",
    "PROTECTION DES CONSOMMATEURS": "escroquerie",
    "PROCES-VERBAL": "preuve",
    "QUESTION PRIORITAIRE DE CONSTITUTIONNALITE": "qpc",
    "RECEL": "escroquerie",
    "RECIDIVE": "recidive",
    "REGLEMENTATION ECONOMIQUE": "escroquerie",
    "RESTITUTION": "indemnisation",
    "SAISIES": "perquisition",
    "SANTE PUBLIQUE": "sante",
    "SECRET PROFESSIONNEL": "vie_privee",
    "SOCIETE": "escroquerie",
    "TERRORISME": "droits_fondamentaux",
    "TRIBUNAL DE POLICE": "competence",
    "UNION EUROPEENNE": "droits_fondamentaux",
    "URBANISME": "urbanisme",
    "EXTRADITION": "immigration",
    "USURPATION DE TITRE OU FONCTION": "corruption",
    "VIOL": "qualification",
    "ÉLECTION": "corruption",
    "ÉLECTIONS": "corruption",
    "Nullité": "nullite",
    "Liberté d'expression": "presse",
    "PROSTITUTION": "sante",
    "TRAVAIL": "droits_defense",
}


def theme_codes_for_official(matters: list[str] | tuple[str, ...] | None) -> list[str]:
    """Codes de thèmes correspondant aux matières officielles de la Cour."""
    codes: list[str] = []
    for matter in matters or ():
        code = OFFICIAL_TO_THEME.get(str(matter).strip())
        if code and code in THEME_INDEX and code not in codes:
            codes.append(code)
    return codes


def _evidence_for(theme: Theme, zones: dict[str, str], limit: int = 2) -> list[str]:
    """Extraits courts justifiant l'attribution du thème."""
    picks: list[str] = []
    for zone in ("motivations", "moyens", "dispositif", "expose"):
        text = zones.get(zone) or ""
        if not text:
            continue
        for sentence in sentences(text):
            if len(sentence) < 45:
                continue
            if any(count_matches(sentence, pattern) for pattern in theme.patterns):
                if any(count_matches(sentence, exclusion) for exclusion in theme.exclude):
                    continue
                candidate = re.sub(r"^\s*\d+\s*[°º)]\s*", "", sentence).strip()
                if candidate and candidate not in picks:
                    picks.append(candidate)
                break
        if len(picks) >= limit:
            break
    return picks


def official_themes(raw_meta: dict[str, Any]) -> list[str]:
    """Nomenclature officielle de la Cour (champ `themes` de Judilibre)."""
    values = raw_meta.get("themes") or []
    if isinstance(values, list):
        return [str(v) for v in values if v]
    return []
