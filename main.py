"""
Bot Discord - Douane RP (Belgique)
Gestion automatique de l'arrivée des joueurs, formulaire RP, filtre anti-troll strict
et choix du statut (Touriste / Diplomate étranger / Citoyen belge).
Conçu pour être hébergé H24 sur un service cloud gratuit.
"""

import os
import re
import unicodedata
import logging

import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web

# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")

# Noms des rôles (doivent correspondre EXACTEMENT à ceux créés sur le serveur)
ROLE_IMMIGRE = "Immigrant"
ROLE_TOURISTE = "Touriste"
ROLE_DIPLOMATE = "Diplomate étranger"
ROLE_CITOYEN = "Citoyen belge 🇧🇪"

SALON_DOUANE = "douane"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("douane-bot")

# ============================================================
# FILTRE ANTI-TROLL (strict)
# ============================================================

# Table de correspondance "langage leet" -> lettres normales (n1qu3 -> nique, etc.)
LEET_TABLE = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "@": "a", "$": "s", "+": "t", "!": "i",
})


def normaliser(texte: str) -> str:
    """Met en minuscule, retire les accents et convertit le langage leet."""
    texte = texte.lower().translate(LEET_TABLE)
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return texte


BLACKLIST_INSULTES = [
    "con", "connard", "connasse", "batard", "salope", "pute", "putain",
    "encule", "enculer", "enculeur", "fdp", "ntm", "tg", "ta gueule",
    "ferme ta gueule", "bouffon", "abruti", "debile", "idiot", "imbecile",
    "cretin", "tare", "attarde", "demeure", "raclure", "ordure", "merde",
    "chier", "nique", "niquer", "enfoire", "pd", "pede", "tapette", "gouine",
    "batard", "clochard", "pouffiasse", "batarde",
]

BLACKLIST_SEXUEL = [
    "sexe", "penis", "bite", "chatte", "couille", "porno", "seins",
    "cul", "branler", "branlette", "orgasme", "masturber", "viol", "violer",
    "sextape", "nudes",
]

BLACKLIST_HAINE = [
    "hitler", "nazi", "raciste", "negro", "nigger", "nigga", "bougnoule",
    "bicot", "chinetoque", "youpin", "feuj", "terroriste", "djihadiste",
    "esclave", "kkk", "singe",
]

BLACKLIST_TROLL = [
    "xxx", "aaa", "azerty", "qwerty", "test", "test123", "admin", "modo",
    "staff", "system", "systeme", "bot", "dieu", "roi", "president",
    "king", "god", "null", "undefined", "asdf", "zxcv", "lorem", "ipsum",
    "kikoo", "lol", "mdr", "xd", "ptdr", "osef", "jsp", "blabla", "gamin",
    "random", "alakon", "troll", "trolldeconnard", "chef", "boss",
    "inconnu", "anonyme", "nom", "prenom", "exemple", "toto", "tata",
    "titi", "bidule", "machin", "truc",
]

BLACKLIST_GLOBAL = [
    normaliser(m) for m in
    (BLACKLIST_INSULTES + BLACKLIST_SEXUEL + BLACKLIST_HAINE + BLACKLIST_TROLL)
]


def contient_mot_interdit(texte: str, blacklist: list[str]) -> str | None:
    """Retourne le premier mot interdit trouvé (recherche sur texte normalisé), sinon None."""
    texte_norm = normaliser(texte)
    for mot in blacklist:
        if re.search(rf"\b{re.escape(mot)}\b", texte_norm):
            return mot
    return None


def ressemble_a_du_charabia(mot: str) -> bool:
    """Détecte les mots-clavier absurdes (zxcvbn, aaaaaa, sans voyelle, etc.)."""
    mot_norm = normaliser(mot)
    if re.search(r"(.)\1{3,}", mot_norm):  # 4+ répétitions du même caractère
        return True
    lettres = re.sub(r"[^a-z]", "", mot_norm)
    if len(lettres) >= 5 and sum(1 for c in lettres if c in "aeiouy") == 0:
        return True
    return False


def valider_nom_prenom(valeur: str) -> tuple[bool, str]:
    valeur = valeur.strip()

    mot_interdit = contient_mot_interdit(valeur, BLACKLIST_GLOBAL)
    if mot_interdit:
        return False, "Nom invalide (contenu inapproprié détecté)."

    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ]+([ '\-][A-Za-zÀ-ÖØ-öø-ÿ]+)+", valeur):
        return False, "Nom invalide (2 mots minimum : Prénom + Nom, lettres uniquement)."

    mots = valeur.split()
    if len(mots) < 2:
        return False, "Nom invalide (2 mots minimum : Prénom + Nom)."

    for mot in mots:
        if ressemble_a_du_charabia(mot):
            return False, "Nom invalide (mot jugé absurde ou aléatoire)."

    return True, ""


def valider_age(valeur: str) -> tuple[bool, str]:
    valeur = valeur.strip()
    if not valeur.isdigit():
        return False, "Âge invalide (doit être un nombre)."
    age = int(valeur)
    if age < 18 or age > 80:
        return False, "Âge invalide (doit être compris entre 18 et 80 ans)."
    return True, ""


def valider_nationalite(valeur: str) -> tuple[bool, str]:
    valeur = valeur.strip()

    mot_interdit = contient_mot_interdit(valeur, BLACKLIST_GLOBAL)
    if mot_interdit:
        return False, "Nationalité invalide (contenu inapproprié détecté)."

    if len(valeur) < 3:
        return False, "Nationalité invalide (3 caractères minimum)."

    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ '\-]+", valeur):
        return False, "Nationalité invalide (lettres uniquement)."

    if ressemble_a_du_charabia(valeur.replace(" ", "")):
        return False, "Nationalité invalide (jugée absurde ou aléatoire)."

    return True, ""


def valider_raison(valeur: str) -> tuple[bool, str]:
    valeur = valeur.strip()

    mot_interdit = contient_mot_interdit(valeur, BLACKLIST_GLOBAL)
    if mot_interdit:
        return False, "Raison de venue invalide (contenu inapproprié détecté)."

    if len(valeur) < 20:
        return False, "Raison de venue invalide (20 caractères minimum)."

    if re.search(r"(.)\1{3,}", normaliser(valeur)):
        return False, "Raison de venue invalide (texte détecté comme spam)."

    mots = valeur.lower().split()
    if len(set(mots)) < max(3, len(mots) // 3):
        return False, "Raison de venue invalide (texte jugé répétitif ou absurde)."

    if sum(1 for m in mots if ressemble_a_du_charabia(m)) > max(1, len(mots) // 4):
        return False, "Raison de venue invalide (trop de mots jugés absurdes)."

    return True, ""


# ============================================================
# INTENTS & BOT
# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ============================================================
# VUE - Choix du statut (après validation de la fiche)
# ============================================================

class VisaSelectView(discord.ui.View):
    def __init__(self, pseudo: str, member_id: int):
        super().__init__(timeout=300)
        self.pseudo = pseudo
        self.member_id = member_id

    @discord.ui.select(
        placeholder="Choisis ton statut...",
        options=[
            discord.SelectOption(label="Touriste", description="Séjour temporaire en Belgique", emoji="🧳", value="touriste"),
            discord.SelectOption(label="Diplomate étranger", description="Représentant officiel d'un pays étranger", emoji="🎩", value="diplomate"),
            discord.SelectOption(label="Citoyen belge", description="Installation définitive en Belgique", emoji="🇧🇪", value="citoyen"),
        ],
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.member_id:
            await interaction.response.send_message("Ce menu ne t'est pas destiné.", ephemeral=True)
            return

        guild = interaction.guild
        member = guild.get_member(self.member_id) or interaction.user
        choix = select.values[0]

        role_map = {
            "touriste": ROLE_TOURISTE,
            "diplomate": ROLE_DIPLOMATE,
            "citoyen": ROLE_CITOYEN,
        }
        nom_role = role_map[choix]
        role_cible = discord.utils.get(guild.roles, name=nom_role)
        role_immigrant = discord.utils.get(guild.roles, name=ROLE_IMMIGRE)

        try:
            if role_immigrant and role_immigrant in member.roles:
                await member.remove_roles(role_immigrant, reason="Fiche RP validée")
            if role_cible:
                await member.add_roles(role_cible, reason="Fiche RP validée")
            try:
                await member.edit(nick=self.pseudo[:32], reason="Fiche RP validée")
            except discord.Forbidden:
                log.warning(f"Impossible de renommer {member}")
        except discord.Forbidden:
            await interaction.response.edit_message(
                content="⚠️ Erreur de permissions : contacte un administrateur.", view=None
            )
            return

        await interaction.response.edit_message(
            content=f"✅ Statut choisi : **{nom_role}**. Bienvenue !", view=None
        )

        try:
            await member.send(
                f"✅ **Bienvenue en Belgique, {self.pseudo} !**\n"
                f"Ton statut **{nom_role}** a été confirmé automatiquement."
            )
        except discord.Forbidden:
            log.warning(f"Impossible d'envoyer un MP de confirmation à {member}")


# ============================================================
# MODAL - Formulaire RP
# ============================================================

class FormulaireRPModal(discord.ui.Modal, title="Fiche RP - Douane Belge"):

    nom_prenom = discord.ui.TextInput(
        label="Nom & Prénom RP", placeholder="Ex : Jean Dupont",
        style=discord.TextStyle.short, max_length=50, required=True,
    )
    age = discord.ui.TextInput(
        label="Âge RP", placeholder="Ex : 27",
        style=discord.TextStyle.short, max_length=3, required=True,
    )
    nationalite = discord.ui.TextInput(
        label="Nationalité RP", placeholder="Ex : Française",
        style=discord.TextStyle.short, max_length=30, required=True,
    )
    raison = discord.ui.TextInput(
        label="Raison de venue",
        placeholder="Explique en quelques phrases pourquoi tu viens en Belgique...",
        style=discord.TextStyle.paragraph, max_length=500, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        member = interaction.user
        erreurs = []

        for valeur, validateur in [
            (self.nom_prenom.value, valider_nom_prenom),
            (self.age.value, valider_age),
            (self.nationalite.value, valider_nationalite),
            (self.raison.value, valider_raison),
        ]:
            ok, msg = validateur(valeur)
            if not ok:
                erreurs.append(msg)

        # ---- CAS REFUSÉ ----
        if erreurs:
            await interaction.response.send_message(
                "❌ Ta fiche RP a été **refusée**. Corrige les points ci-dessous et réessaie via le bouton.",
                ephemeral=True,
            )
            try:
                texte_erreurs = "\n".join(f"• {e}" for e in erreurs)
                await member.send(
                    f"❌ **Ta fiche RP a été refusée à la douane.**\n\nMotif(s) :\n{texte_erreurs}\n\n"
                    f"Merci de retenter en cliquant à nouveau sur **« Remplir ma fiche RP »** dans #{SALON_DOUANE}."
                )
            except discord.Forbidden:
                log.warning(f"Impossible d'envoyer un MP de refus à {member}")
            return

        # ---- CAS VALIDÉ : on demande le statut avant d'attribuer un rôle ----
        nouveau_pseudo = self.nom_prenom.value.strip().title()
        await interaction.response.send_message(
            "✅ Ta fiche RP est **valide** ! Choisis maintenant ton statut :",
            view=VisaSelectView(pseudo=nouveau_pseudo, member_id=member.id),
            ephemeral=True,
        )


# ============================================================
# VUE - Bouton persistant "Remplir ma fiche RP"
# ============================================================

class DouaneView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Remplir ma fiche RP", style=discord.ButtonStyle.green,
        emoji="📋", custom_id="douane:remplir_fiche",
    )
    async def remplir_fiche(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FormulaireRPModal())


# ============================================================
# ÉVÉNEMENTS
# ============================================================

@bot.event
async def on_ready():
    bot.add_view(DouaneView())
    log.info(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        log.info(f"{len(synced)} commande(s) slash synchronisée(s).")
    except Exception as e:
        log.error(f"Erreur de synchronisation des commandes : {e}")


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild

    role_immigrant = discord.utils.get(guild.roles, name=ROLE_IMMIGRE)
    if role_immigrant:
        try:
            await member.add_roles(role_immigrant, reason="Arrivée sur le serveur")
        except discord.Forbidden:
            log.error(f"Impossible d'attribuer le rôle {ROLE_IMMIGRE} à {member}.")
    else:
        log.error(f"Rôle '{ROLE_IMMIGRE}' introuvable sur le serveur {guild.name}.")

    # Message de bienvenue en MP (privé, n'encombre pas le salon)
    try:
        await member.send(
            f"👋 **Bienvenue en Belgique, {member.name} !**\n\n"
            f"Rends-toi dans le salon **#{SALON_DOUANE}** et clique sur le bouton "
            f"**« Remplir ma fiche RP »** pour passer la douane."
        )
    except discord.Forbidden:
        # Si le membre a bloqué les MP, on prévient dans le salon puis on efface vite le message
        salon = discord.utils.get(guild.text_channels, name=SALON_DOUANE)
        if salon:
            try:
                msg = await salon.send(
                    f"👋 {member.mention}, active tes messages privés ou clique directement sur "
                    f"**« Remplir ma fiche RP »** ci-dessus pour passer la douane."
                )
                await msg.delete(delay=20)
            except discord.Forbidden:
                log.warning(f"Impossible d'envoyer un message dans #{SALON_DOUANE}")


# ============================================================
# COMMANDE SLASH - Poster le message de douane avec le bouton
# ============================================================

@bot.tree.command(name="setup_douane", description="Poste le message avec le bouton de fiche RP dans ce salon (admin uniquement).")
@app_commands.checks.has_permissions(administrator=True)
async def setup_douane(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛂 Douane du Royaume de Belgique",
        description=(
            "Bienvenue voyageur !\n\n"
            "Pour entrer sur le territoire belge, tu dois remplir une fiche d'identité RP.\n"
            "Clique sur le bouton ci-dessous pour commencer.\n\n"
            "Une fois ta fiche validée, tu choisiras ton statut : 🧳 Touriste, 🎩 Diplomate étranger "
            "ou 🇧🇪 Citoyen belge.\n\n"
            "⚠️ Toute tentative de troll (nom absurde, âge invalide, insultes...) sera "
            "automatiquement rejetée et tu resteras bloqué à la douane."
        ),
        color=discord.Color.gold(),
    )
    await interaction.channel.send(embed=embed, view=DouaneView())
    await interaction.response.send_message("✅ Message de douane posté.", ephemeral=True)


@setup_douane.error
async def setup_douane_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Tu dois être administrateur pour utiliser cette commande.", ephemeral=True)
    else:
        log.error(f"Erreur setup_douane : {error}")


# ============================================================
# MICRO SERVEUR WEB (keep-alive pour Render / Koyeb / Railway)
# ============================================================

async def handle_ping(request):
    return web.Response(text="Le bot de douane est en ligne ✅")


async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Serveur web keep-alive démarré sur le port {port}")


async def main():
    async with bot:
        await start_webserver()
        await bot.start(TOKEN)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("La variable d'environnement DISCORD_TOKEN n'est pas définie.")
    import asyncio
    asyncio.run(main())
