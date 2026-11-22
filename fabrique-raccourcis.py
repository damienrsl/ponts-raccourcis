#!/usr/bin/env python3
"""Fabrique les raccourcis iOS « ponts » vers Tokn (fichiers .shortcut signés, 1 tap pour installer).

Chaque raccourci = 2 à 5 actions natives de l'app Raccourcis, sans code serveur : il parle à
POST /api/widget/action (le même point d'entrée que les widgets Scriptable), avec le jeton de widget
de Damien dans l'en-tête X-Tokn-Widget. Le jeton est lu sur le cerveau (ssh), jamais écrit ailleurs
que dans raccourcis/ (dossier hors git).

    python3 fabrique-raccourcis.py            # écrit raccourcis/<Nom>.shortcut (signés « anyone »)
    TOKN_JETON=xxx python3 fabrique-raccourcis.py   # sans ssh

Vérification possible ici : `shortcuts sign` refuse un plist qui n'est pas un raccourci valide.
Le rendu sur l'iPhone n'est pas vérifiable depuis le Mac.
"""
import os, plistlib, subprocess, sys, uuid, json

ICI = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ICI, "raccourcis")
TOKN = os.environ.get("TOKN_URL", "http://100.125.157.100:8791")
SSH = os.path.expanduser("~/.local/share/damienprime/cerveau/ssh")
ORANGE = 4271458815   # couleur d'icône Raccourcis (DA iPhone : orange cosmique)


def jeton():
    j = os.environ.get("TOKN_JETON")
    if j:
        return j
    r = subprocess.run([SSH, "cat ~/tokn-data/widget-jetons.json"], capture_output=True, text=True, timeout=30)
    d = json.loads(r.stdout.strip() or "{}")
    if not d.get("damien"):
        sys.exit("jeton de widget introuvable sur le cerveau")
    return d["damien"]


# ---------- briques du format Raccourcis ----------
def texte(s):
    """Une chaîne constante (WFTextTokenString sans variable)."""
    return {"Value": {"string": s, "attachmentsByRange": {}}, "WFSerializationType": "WFTextTokenString"}


def variable(uid, nom, prefixe="", suffixe=""):
    """Une chaîne qui contient la sortie d'une action précédente (le caractère U+FFFC est la pièce jointe)."""
    s = prefixe + "￼" + suffixe
    return {"Value": {"string": s, "attachmentsByRange": {"{%d, 1}" % len(prefixe): {"Type": "ActionOutput", "OutputUUID": uid, "OutputName": nom}}},
            "WFSerializationType": "WFTextTokenString"}


def entree_raccourci(prefixe="", suffixe=""):
    s = prefixe + "￼" + suffixe
    return {"Value": {"string": s, "attachmentsByRange": {"{%d, 1}" % len(prefixe): {"Type": "ExtensionInput"}}}, "WFSerializationType": "WFTextTokenString"}


def piece(uid, nom):
    """Une pièce jointe seule (pour WFInput)."""
    return {"Value": {"Type": "ActionOutput", "OutputUUID": uid, "OutputName": nom}, "WFSerializationType": "WFTextTokenAttachment"}


def piece_entree():
    return {"Value": {"Type": "ExtensionInput"}, "WFSerializationType": "WFTextTokenAttachment"}


def dico(items):
    """Un dictionnaire Raccourcis : items = [(clé, valeur WFTextTokenString)]."""
    return {"Value": {"WFDictionaryFieldValueItems": [{"WFItemType": 0, "WFKey": texte(k), "WFValue": v} for k, v in items]},
            "WFSerializationType": "WFDictionaryFieldValue"}


def action(identifiant, **params):
    uid = params.pop("uid", None) or str(uuid.uuid4()).upper()
    params["UUID"] = uid
    return {"WFWorkflowActionIdentifier": identifiant, "WFWorkflowActionParameters": params}, uid


def dicter(arret="After Pause"):
    return action("is.workflow.actions.dictatetext", WFDictateTextStopListening=arret, WFSpeechLanguage="fr-FR")


def demander(question):
    return action("is.workflow.actions.ask", WFAskActionPrompt=question, WFInputType="Text", WFAllowsMultilineText=True)


def appel_tokn(J, champs):
    """POST /api/widget/action avec le jeton ; champs = [(clé, WFTextTokenString)]."""
    return action("is.workflow.actions.downloadurl",
                  WFURL=TOKN + "/api/widget/action", WFHTTPMethod="POST", WFHTTPBodyType="JSON", ShowHeaders=True,
                  WFHTTPHeaders=dico([("X-Tokn-Widget", texte(J)), ("Content-Type", texte("application/json"))]),
                  WFJSONValues=dico(champs))


def valeur(uid_source, cle):
    return action("is.workflow.actions.getvalueforkey", WFDictionaryKey=cle, WFGetDictionaryValueType="Value",
                  WFInput=piece(uid_source, "Contents of URL"))


def notifier(uid_valeur, titre="Tokn"):
    return action("is.workflow.actions.notification", WFNotificationActionTitle=titre,
                  WFNotificationActionBody=variable(uid_valeur, "Dictionary Value"), WFNotificationActionSound=False)


def raccourci(actions, glyphe=59511, entrees=None, sans_entree=None):
    r = {
        "WFWorkflowClientVersion": "2607.1.3",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": ORANGE, "WFWorkflowIconGlyphNumber": glyphe},
        "WFWorkflowImportQuestions": [],
        "WFWorkflowTypes": ["NCWidget", "WatchKit"] + (["ActionExtension"] if entrees else []),
        "WFWorkflowInputContentItemClasses": entrees or [],
        "WFWorkflowHasShortcutInputVariables": bool(entrees),
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowActions": actions,
    }
    if sans_entree:
        r["WFWorkflowNoInputBehavior"] = {"Name": "WFWorkflowNoInputBehaviorAskForInput", "Parameters": {"ItemClass": sans_entree}}
    return r


# ---------- les ponts de la vague 1 ----------
def pont_dictee(J, act, glyphe, espace=None, arret="After Pause"):
    """Dicter → action Tokn (prompt / selection / vocal / dismoi) → notification avec la réponse du serveur."""
    a1, u1 = dicter(arret)
    champs = [("action", texte(act)), ("texte", variable(u1, "Dictated Text"))]
    if espace:
        champs.append(("espace", texte(espace)))
    a2, u2 = appel_tokn(J, champs)
    a3, u3 = valeur(u2, "message")
    a4, _ = notifier(u3)
    return raccourci([a1, a2, a3, a4], glyphe)


def pont_lien(J):
    """Depuis la feuille de partage (lien ou texte) : Claude reçoit le lien, dit ce qu'il en fait."""
    a1, u1 = appel_tokn(J, [("action", texte("prompt")),
                            ("texte", entree_raccourci("Regarde ce que je te partage depuis l'iPhone et dis-moi ce que tu en fais (idée, produit, concurrent, à ranger) : "))])
    a2, u2 = valeur(u1, "message")
    a3, _ = notifier(u2)
    return raccourci([a1, a2, a3], 59511, entrees=["WFURLContentItem", "WFStringContentItem", "WFSafariWebPageContentItem", "WFArticleContentItem"])


def pont_photo(J):
    """Une photo (partagée, ou choisie si lancé à la main) + quelques mots → sujet Tokn avec l'image jointe."""
    a1, u1 = action("is.workflow.actions.image.resize", WFImageResizeWidth="1400", WFImageResizeHeight="", WFInput=piece_entree())
    a2, u2 = action("is.workflow.actions.image.convert", WFImageFormat="JPEG", WFImageCompressionQuality=0.8, WFImagePreserveMetadata=False,
                    WFInput=piece(u1, "Resized Image"))
    a3, u3 = action("is.workflow.actions.base64encode", WFEncodeMode="Encode", WFBase64LineBreakMode="None", WFInput=piece(u2, "Converted Image"))
    a4, u4 = demander("Quelques mots pour Claude ?")
    a5, u5 = appel_tokn(J, [("action", texte("photo")), ("image_b64", variable(u3, "Base64 Encoded")), ("nom", texte("iphone.jpg")),
                            ("texte", variable(u4, "Provided Input"))])
    a6, u6 = valeur(u5, "message")
    a7, _ = notifier(u6)
    return raccourci([a1, a2, a3, a4, a5, a6, a7], 59511, entrees=["WFImageContentItem"], sans_entree="WFImageContentItem")


def pont_minuteur(J, minutes=25):
    a1, u1 = demander("Sur quoi, pendant %d min ?" % minutes)
    a2, u2 = appel_tokn(J, [("action", texte("minuteur")), ("titre", variable(u1, "Provided Input")), ("min", texte(str(minutes)))])
    a3, u3 = valeur(u2, "message")
    a4, _ = notifier(u3)
    return raccourci([a1, a2, a3, a4], 59511)


PONTS = {
    "Tokn": lambda J: pont_dictee(J, "prompt", 59511),
    "Sélection": lambda J: pont_dictee(J, "selection", 59511),
    "Vocal long": lambda J: pont_dictee(J, "vocal", 59511, arret="On Tap"),
    "Dis-moi": lambda J: pont_dictee(J, "dismoi", 59511),
    "Lien à Claude": pont_lien,
    "Photo à Claude": pont_photo,
    "Minuteur 25": lambda J: pont_minuteur(J, 25),
}


def main():
    J = jeton()
    os.makedirs(OUT, exist_ok=True)
    faits = []
    for nom, fab in PONTS.items():
        brut = os.path.join(OUT, nom + ".brut.shortcut")
        signe = os.path.join(OUT, nom + ".shortcut")
        with open(brut, "wb") as f:
            plistlib.dump(fab(J), f)
        r = subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", brut, "--output", signe], capture_output=True, text=True)
        os.replace(brut, brut)  # le brut reste pour relecture (même dossier hors git)
        if r.returncode != 0 or not os.path.exists(signe):
            print("ÉCHEC", nom, r.stderr.strip() or r.stdout.strip())
            continue
        faits.append((nom, os.path.getsize(signe)))
        os.chmod(signe, 0o600)
    for nom, taille in faits:
        print("OK  %-16s %6d octets" % (nom, taille))
    print("%d/%d raccourcis signés dans %s" % (len(faits), len(PONTS), OUT))


if __name__ == "__main__":
    main()
