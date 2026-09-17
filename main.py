"""
Bot Discord - Douane RP (Belgique)
Gestion automatique de l'arrivée des joueurs, formulaire RP et validation anti-troll.
Conçu pour être hébergé H24 sur un service cloud gratuit (Render, Koyeb, Railway...).
"""

import os
import re
import logging

import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web

# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN")  # Le token est fourni via une variable d'environnement (jamais en dur dans le code)

# Noms des rôles (adapte-les si besoin, ou remplace par des IDs pour plus de fiabilité)
ROLE_IMMIGRE = "Immigré"
ROLE_CITOYEN = "Citoyen belge"

# Nom du salon douane
SALON_DOUANE = "douane"

# Liste noire de mots interdits / insultes / mots absurdes pour le filtre anti-troll
# (liste volontairement générique, à compléter selon ton serveur)
BLACKLIST = [
    "xxx", "aaa", "azerty", "qwerty", "test123", "ptn", "nique", "merde",
    "con", "connard", "batard", "salope", "pute", "enculé", "enculer",
    "ntm", "tg", "ta gueule", "trollpays", "troll", "penis", "bite",
    "chatte", "sexe", "drogue", "hitler", "nazi", "raciste", "négro",
    "nigger", "fdp", "pd", "gay lol", "kikoo", "lol", "mdr", "xd",
    "blabla", "jsp", "osef", "nul", "gamin",
]

# Mots interdits spécifiques pour le champ "Nom & Prénom" (en plus du filtre général)
BLACKLIST_NOM = BLACKLIST + ["admin", "modo", "staff", "system", "bot", "dieu", "roi", "president"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("douane-bot")

# ============================================================
# INTENTS & BOT
# ============================================================

intents = discord.Intents.default()
intents.members = True          # requis pour on_member_join et modifier les rôles/pseudos
intents.message_content = True  # requis si tu ajoutes des commandes textuelles plus tard

bot = commands.Bot(command_prefix="!", intents=intents)


# ============================================================
# FONCTIONS DE VALIDATION (Anti-Troll)
# ============================================================

def contient_mot_interdit(texte: str, blacklist: list[str]) -> str | None:
    """Retourne le premier mot interdit trouvé dans le texte, sinon None."""
    texte_lower = texte.lower()
    for mot in blacklist:
        if re.search(rf"\b{re.escape(mot)}\b", texte_lower):
            return mot
    return None


def valider_nom_prenom(valeur: str) -> tuple[bool, str]:
    valeur = valeur.strip()

    mot_interdit = contient_mot_interdit(valeur, BLACKLIST_NOM)
    if mot_interdit:
        return False, f"Nom invalide (contenu inapproprié détecté : '{mot_interdit}')."

    # Uniquement lettres, espaces, tirets et apostrophes (accents compris)
    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ]+([ '\-][A-Za-zÀ-ÖØ-öø-ÿ]+)+", valeur):
        return False, "Nom invalide (doit contenir un Prénom ET un Nom, sans chiffres ni caractères spéciaux)."

    mots = valeur.split()
    if len(mots) < 2:
        return False, "Nom invalide (2 mots minimum : Prénom + Nom)."

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

    mot_interdit = contient_mot_interdit(valeur, BLACKLIST)
    if mot_interdit:
        return False, f"Nationalité invalide (contenu inapproprié détecté : '{mot_interdit}')."

    if len(valeur) < 3:
        return False, "Nationalité invalide (3 caractères minimum)."

    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ '\-]+", valeur):
        return False, "Nationalité invalide (lettres uniquement)."

    return True, ""


def valider_raison(valeur: str) -> tuple[bool, str]:
    valeur = valeur.strip()

    mot_interdit = contient_mot_interdit(valeur, BLACKLIST)
    if mot_interdit:
        return False, f"Raison de venue invalide (contenu inapproprié détecté : '{mot_interdit}')."

    if len(valeur) < 20:
        return False, "Raison de venue invalide (20 caractères minimum, réponse trop courte ou vide de sens)."

    # Anti-spam basique : évite les répétitions du même caractère (ex: "aaaaaaaaaaaaaaaaaaaa")
    if re.search(r"(.)\1{6,}", valeur):
        return False, "Raison de venue invalide (texte détecté comme spam/absurde)."

    # Vérifie qu'il y a un minimum de mots distincts (évite "test test test test...")
    mots = valeur.lower().split()
    if len(set(mots)) < max(3, len(mots) // 3):
        return False, "Raison de venue invalide (texte jugé absurde ou répétitif)."

    return True, ""


# ============================================================
# MODAL - Formulaire RP
# ============================================================

class FormulaireRPModal(discord.ui.Modal, title="Fiche RP - Douane Belge"):

    nom_prenom = discord.ui.TextInput(
        label="Nom & Prénom RP",
        placeholder="Ex : Jean Dupont",
        style=discord.TextStyle.short,
        max_length=50,
        required=True,
    )
    age = discord.ui.TextInput(
        label="Âge RP",
        placeholder="Ex : 27",
        style=discord.TextStyle.short,
        max_length=3,
        required=True,
    )
    nationalite = discord.ui.TextInput(
        label="Nationalité RP",
        placeholder="Ex : Française",
        style=discord.TextStyle.short,
        max_length=30,
        required=True,
    )
    raison = discord.ui.TextInput(
        label="Raison de venue",
        placeholder="Explique en quelques phrases pourquoi tu viens en Belgique...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        member = interaction.user
        guild = interaction.guild

        erreurs = []

        ok, msg = valider_nom_prenom(self.nom_prenom.value)
        if not ok:
            erreurs.append(msg)

        ok, msg = valider_age(self.age.value)
        if not ok:
            erreurs.append(msg)

        ok, msg = valider_nationalite(self.nationalite.value)
        if not ok:
            erreurs.append(msg)

        ok, msg = valider_raison(self.raison.value)
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
                    f"❌ **Ta fiche RP a été refusée à la douane.**\n\n"
                    f"Motif(s) :\n{texte_erreurs}\n\n"
                    f"Merci de retenter en cliquant à nouveau sur **« Remplir ma fiche RP »** dans #{SALON_DOUANE}."
                )
            except discord.Forbidden:
                log.warning(f"Impossible d'envoyer un MP de refus à {member}")
            return

        # ---- CAS VALIDÉ ----
        role_immigre = discord.utils.get(guild.roles, name=ROLE_IMMIGRE)
        role_citoyen = discord.utils.get(guild.roles, name=ROLE_CITOYEN)

        try:
            if role_immigre and role_immigre in member.roles:
                await member.remove_roles(role_immigre, reason="Fiche RP validée")
            if role_citoyen:
                await member.add_roles(role_citoyen, reason="Fiche RP validée")

            nouveau_pseudo = self.nom_prenom.value.strip().title()
            try:
                await member.edit(nick=nouveau_pseudo[:32], reason="Fiche RP validée")
            except discord.Forbidden:
                log.warning(f"Impossible de renommer {member} (permissions insuffisantes, ex: rôle propriétaire)")

        except discord.Forbidden:
            await interaction.response.send_message(
                "⚠️ Erreur de permissions : le bot n'a pas pu attribuer les rôles. Contacte un administrateur.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ Ta fiche RP a été **acceptée** ! Bienvenue en Belgique. Consulte tes messages privés.",
            ephemeral=True,
        )

        try:
            await member.send(
                f"✅ **Bienvenue en Belgique, {nouveau_pseudo} !**\n\n"
                f"Ta fiche RP a été validée automatiquement.\n"
                f"Tu es désormais **{ROLE_CITOYEN}** et tu as accès au reste du serveur."
            )
        except discord.Forbidden:
            log.warning(f"Impossible d'envoyer un MP de confirmation à {member}")


# ============================================================
# VUE - Bouton persistant "Remplir ma fiche RP"
# ============================================================

class DouaneView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # timeout=None => bouton persistant, fonctionne même après redémarrage

    @discord.ui.button(
        label="Remplir ma fiche RP",
        style=discord.ButtonStyle.green,
        emoji="📋",
        custom_id="douane:remplir_fiche",  # custom_id fixe requis pour la persistance
    )
    async def remplir_fiche(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FormulaireRPModal())


# ============================================================
# ÉVÉNEMENTS
# ============================================================

@bot.event
async def on_ready():
    bot.add_view(DouaneView())  # ré-enregistre la vue persistante après un redémarrage
    log.info(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        log.info(f"{len(synced)} commande(s) slash synchronisée(s).")
    except Exception as e:
        log.error(f"Erreur de synchronisation des commandes : {e}")


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild

    role_immigre = discord.utils.get(guild.roles, name=ROLE_IMMIGRE)
    if role_immigre:
        try:
            await member.add_roles(role_immigre, reason="Arrivée sur le serveur")
        except discord.Forbidden:
            log.error(f"Impossible d'attribuer le rôle {ROLE_IMMIGRE} à {member} (permissions insuffisantes).")
    else:
        log.error(f"Rôle '{ROLE_IMMIGRE}' introuvable sur le serveur {guild.name}.")

    salon = discord.utils.get(guild.text_channels, name=SALON_DOUANE)
    if salon:
        try:
            await salon.send(
                f"👋 Bienvenue {member.mention} ! Rends-toi à la douane et clique sur "
                f"**« Remplir ma fiche RP »** pour entrer en Belgique."
            )
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
    port = int(os.getenv("PORT", 8080))  # Render/Koyeb fournissent le port via cette variable
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
