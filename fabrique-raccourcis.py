#!/usr/bin/env python3
"""Fabrique les raccourcis iOS « ponts » vers Tokn et Calories (fichiers .shortcut signés, 1 tap pour installer).

Chaque raccourci = 2 à 7 actions natives de l'app Raccourcis, sans code serveur côté iPhone : il parle à
POST /api/widget/action (le même point d'entrée que les widgets Scriptable), avec le jeton de widget
de Damien dans l'en-tête X-Tokn-Widget ; les ponts Calories envoient le cookie de l'app. Les jetons sont
lus sur le cerveau (ssh), jamais écrits ailleurs que dans raccourcis/ (dossier hors git).

    python3 fabrique-raccourcis.py            # écrit raccourcis/<Nom>.shortcut (signés « anyone »)
    TOKN_JETON=xxx CALO_JETON=yyy python3 fabrique-raccourcis.py   # sans ssh

Pièges : `shortcuts sign` exige une entrée qui finit en .shortcut (sinon « incorrect format ») ; il valide
la structure, pas le rendu : seul l'iPhone dit si l'import est propre.
Vague 1 (22/11) : Tokn, Sélection, Vocal long, Dis-moi, Lien à Claude, Photo à Claude, Minuteur 25.
Vague 2 (22/11) : Reprendre, Le point, Stop mission, Dis-moi lu, Radar, Brief du matin, Repas dicté.
"""
import os, plistlib, subprocess, sys, uuid, json

ICI = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ICI, "raccourcis")
TOKN = os.environ.get("TOKN_URL", "http://100.125.157.100:8791")
CALO = os.environ.get("CALO_URL", "http://100.125.157.100:8793")
SSH = os.path.expanduser("~/.local/share/damienprime/cerveau/ssh")
ORANGE = 4271458815   # couleur d'icône Raccourcis (DA iPhone : orange cosmique)


def _ssh(cmd):
    r = subprocess.run([SSH, cmd], capture_output=True, text=True, timeout=40)
    return r.stdout.strip()


def jeton():
    j = os.environ.get("TOKN_JETON")
    if j:
        return j
    d = json.loads(_ssh("cat ~/tokn-data/widget-jetons.json") or "{}")
    if not d.get("damien"):
        sys.exit("jeton de widget introuvable sur le cerveau")
    return d["damien"]


def jeton_calories():
    j = os.environ.get("CALO_JETON")
    if j:
        return j
    l = json.loads(_ssh("cat ~/apps/calories/data/jetons.json") or "[]")
    if not l:
        sys.exit("jeton Calories introuvable sur le cerveau")
    return sorted(l)[0]


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


def appel_json(url, entetes, champs):
    """POST JSON ; entetes et champs = [(clé, WFTextTokenString)]."""
    return action("is.workflow.actions.downloadurl", WFURL=url, WFHTTPMethod="POST", WFHTTPBodyType="JSON", ShowHeaders=True,
                  WFHTTPHeaders=dico(entetes), WFJSONValues=dico(champs))


def appel_tokn(J, champs):
    return appel_json(TOKN + "/api/widget/action", [("X-Tokn-Widget", texte(J)), ("Content-Type", texte("application/json"))], champs)


def appel_calo(C, route, champs):
    return appel_json(CALO + route, [("Cookie", texte("calories=" + C)), ("Content-Type", texte("application/json"))], champs)


def valeur(uid_source, cle):
    return action("is.workflow.actions.getvalueforkey", WFDictionaryKey=cle, WFGetDictionaryValueType="Value",
                  WFInput=piece(uid_source, "Contents of URL"))


def notifier(uid_valeur, titre="Tokn"):
    return action("is.workflow.actions.notification", WFNotificationActionTitle=titre,
                  WFNotificationActionBody=variable(uid_valeur, "Dictionary Value"), WFNotificationActionSound=False)


def enoncer(uid_valeur):
    return action("is.workflow.actions.speaktext", WFText=variable(uid_valeur, "Dictionary Value"), WFSpeakTextLanguage="fr-FR",
                  WFSpeakTextWait=True, WFSpeakTextRate=0.5, WFSpeakTextPitch=1.0)


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


# ---------- vague 1 ----------
def pont_dictee(J, act, espace=None, arret="After Pause", extra=()):
    """Dicter → action Tokn → notification avec la réponse du serveur."""
    a1, u1 = dicter(arret)
    champs = [("action", texte(act)), ("texte", variable(u1, "Dictated Text"))] + list(extra)
    if espace:
        champs.append(("espace", texte(espace)))
    a2, u2 = appel_tokn(J, champs)
    a3, u3 = valeur(u2, "message")
    a4, _ = notifier(u3)
    return raccourci([a1, a2, a3, a4])


def pont_lien(J):
    a1, u1 = appel_tokn(J, [("action", texte("prompt")),
                            ("texte", entree_raccourci("Regarde ce que je te partage depuis l'iPhone et dis-moi ce que tu en fais (idée, produit, concurrent, à ranger) : "))])
    a2, u2 = valeur(u1, "message")
    a3, _ = notifier(u2)
    return raccourci([a1, a2, a3], entrees=["WFURLContentItem", "WFStringContentItem", "WFSafariWebPageContentItem", "WFArticleContentItem"])


def pont_photo(J):
    a1, u1 = action("is.workflow.actions.image.resize", WFImageResizeWidth="1400", WFImageResizeHeight="", WFInput=piece_entree())
    a2, u2 = action("is.workflow.actions.image.convert", WFImageFormat="JPEG", WFImageCompressionQuality=0.8, WFImagePreserveMetadata=False,
                    WFInput=piece(u1, "Resized Image"))
    a3, u3 = action("is.workflow.actions.base64encode", WFEncodeMode="Encode", WFBase64LineBreakMode="None", WFInput=piece(u2, "Converted Image"))
    a4, u4 = demander("Quelques mots pour Claude ?")
    a5, u5 = appel_tokn(J, [("action", texte("photo")), ("image_b64", variable(u3, "Base64 Encoded")), ("nom", texte("iphone.jpg")),
                            ("texte", variable(u4, "Provided Input"))])
    a6, u6 = valeur(u5, "message")
    a7, _ = notifier(u6)
    return raccourci([a1, a2, a3, a4, a5, a6, a7], entrees=["WFImageContentItem"], sans_entree="WFImageContentItem")


def pont_minuteur(J, minutes=25):
    a1, u1 = demander("Sur quoi, pendant %d min ?" % minutes)
    a2, u2 = appel_tokn(J, [("action", texte("minuteur")), ("titre", variable(u1, "Provided Input")), ("min", texte(str(minutes)))])
    a3, u3 = valeur(u2, "message")
    a4, _ = notifier(u3)
    return raccourci([a1, a2, a3, a4])


# ---------- vague 2 (22/11) : gestes sans id, réponse lue, Radar, brief, Calories ----------
def pont_simple(J, act, cle="message", parler=False, extra=()):
    """Un POST sans dictée (Le point, Stop, Radar) → notification, et Siri lit la clé si parler."""
    a1, u1 = appel_tokn(J, [("action", texte(act))] + list(extra))
    a2, u2 = valeur(u1, cle)
    actions = [a1, a2]
    if parler:
        a3, _ = enoncer(u2)
        actions.append(a3)
    a4, _ = notifier(u2)
    actions.append(a4)
    return raccourci(actions)


def pont_dismoi_lu(J):
    """Dicter → dismoi en attendant la réponse (45 s) → Siri la lit → notification."""
    a1, u1 = dicter()
    a2, u2 = appel_tokn(J, [("action", texte("dismoi")), ("texte", variable(u1, "Dictated Text")), ("attendre", texte("45"))])
    a3, u3 = valeur(u2, "reponse")
    a4, _ = enoncer(u3)
    a5, _ = notifier(u3)
    return raccourci([a1, a2, a3, a4, a5])


def pont_brief(J):
    """Le brief audio du matin : POST brief → audio_b64 → décoder → lire le son."""
    a1, u1 = appel_tokn(J, [("action", texte("brief"))])
    a2, u2 = valeur(u1, "audio_b64")
    a3, u3 = action("is.workflow.actions.base64encode", WFEncodeMode="Decode", WFInput=piece(u2, "Dictionary Value"))
    a4, _ = action("is.workflow.actions.playsound", WFInput=piece(u3, "Base64 Encoded"))
    return raccourci([a1, a2, a3, a4])


def pont_repas(C):
    """Dicter le repas → Calories /api/texte (enregistré direct) → notification des repas notés."""
    a1, u1 = dicter("On Tap")
    a2, u2 = appel_calo(C, "/api/texte", [("texte", variable(u1, "Dictated Text")), ("enregistre", texte("1"))])
    a3, u3 = valeur(u2, "enregistres")
    a4, _ = notifier(u3, titre="Calories · noté")
    return raccourci([a1, a2, a3, a4])


PONTS = {
    # vague 1
    "Tokn": lambda J, C: pont_dictee(J, "prompt"),
    "Sélection": lambda J, C: pont_dictee(J, "selection"),
    "Vocal long": lambda J, C: pont_dictee(J, "vocal", arret="On Tap"),
    "Dis-moi": lambda J, C: pont_dictee(J, "dismoi"),
    "Lien à Claude": lambda J, C: pont_lien(J),
    "Photo à Claude": lambda J, C: pont_photo(J),
    "Minuteur 25": lambda J, C: pont_minuteur(J, 25),
    # vague 2
    "Reprendre": lambda J, C: pont_dictee(J, "continuer", extra=[("id", texte("dernier"))]),
    "Le point": lambda J, C: pont_simple(J, "point"),
    "Stop mission": lambda J, C: pont_simple(J, "stop"),
    "Dis-moi lu": lambda J, C: pont_dismoi_lu(J),
    "Radar": lambda J, C: pont_simple(J, "radar", cle="parle", parler=True),
    "Brief du matin": lambda J, C: pont_brief(J),
    "Repas dicté": lambda J, C: pont_repas(C),
}


def main():
    J, C = jeton(), jeton_calories()
    os.makedirs(OUT, exist_ok=True)
    faits = []
    for nom, fab in PONTS.items():
        brut = os.path.join(OUT, nom + ".brut.shortcut")
        signe = os.path.join(OUT, nom + ".shortcut")
        with open(brut, "wb") as f:
            plistlib.dump(fab(J, C), f)
        r = subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", brut, "--output", signe], capture_output=True, text=True)
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
