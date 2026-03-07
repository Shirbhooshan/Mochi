import discord
from discord.ext import commands, tasks
import sqlite3
import instaloader
import asyncio
import os
import random
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN       = os.getenv("DISCORD_TOKEN")
CHECK_EVERY = 30   # minutes between Instagram checks
PREFIX      = "m!"

# ── Mochi personality lines ───────────────────────────────────────────────────
MOCHI_INTROS = [
    "🦇 *flutters in* eek! {name} just posted something amazing!!",
    "🍡 mochi spotted new art from **{name}**!! squeee~",
    "✨ *hangs upside down excitedly* {name} dropped something!! go look go look!!",
    "🦇 nya~! mochi found fresh art from **{name}**! don't miss it!!",
    "🍡 *swoops in* HELLO!! {name} posted!! mochi is SO excited rn!!",
    "🌙 the art bats have spoken... **{name}** has a new post!! 🦇✨",
]

MOCHI_CAPTIONS = [
    "mochi gives this {hearts} out of 🍡🍡🍡🍡🍡",
    "mochi screamed a little (a lot) when she saw this 🦇",
    "adding this to mochi's cave wall immediately 🖼️",
    "mochi demands you go leave a like RIGHT NOW 🦇💕",
    "this is going in the hall of fame. mochi has decided. 🍡",
]

def mochi_intro(username):
    return random.choice(MOCHI_INTROS).format(name=f"@{username}")

def mochi_caption():
    hearts = random.choice(["💜💜💜💜💜", "💜💜💜💜🤍", "💜💜💜🤍🤍"])
    return random.choice(MOCHI_CAPTIONS).format(hearts=hearts)

# ── Database ──────────────────────────────────────────────────────────────────
def db_connect():
    conn = sqlite3.connect("mochi.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            discord_id   TEXT NOT NULL,
            discord_name TEXT NOT NULL,
            instagram    TEXT NOT NULL,
            last_post_id TEXT,
            added_at     TEXT NOT NULL,
            PRIMARY KEY (discord_id, instagram)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id    TEXT PRIMARY KEY,
            art_channel TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def get_art_channel(guild_id: int) -> int | None:
    conn = db_connect()
    row = conn.execute(
        "SELECT art_channel FROM guild_settings WHERE guild_id=?",
        (str(guild_id),)
    ).fetchone()
    conn.close()
    return int(row[0]) if row else None

def set_art_channel(guild_id: int, channel_id: int):
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO guild_settings (guild_id, art_channel) VALUES (?, ?)",
        (str(guild_id), str(channel_id))
    )
    conn.commit()
    conn.close()

# ── Instaloader setup ─────────────────────────────────────────────────────────
L = instaloader.Instaloader(
    download_pictures=True,
    download_videos=False,
    download_video_thumbnails=False,
    download_geotags=False,
    download_comments=False,
    save_metadata=False,
    quiet=True,
)
# Optional: log into Instagram for better rate limits
# L.login("your_ig_username", "your_ig_password")

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ── Commands ──────────────────────────────────────────────────────────────────

@bot.command(name="add")
async def add_account(ctx, link: str = None):
    """m!add <instagram_link_or_username> — register your Instagram"""
    if link is None:
        await ctx.send(
            "🦇 *blinks* mochi needs a link or username!\n"
            "Usage: `m!add https://instagram.com/yourname` or `m!add yourname`"
        )
        return

    # Extract username from URL or plain text
    username = link.strip("/").split("/")[-1].replace("@", "").lower()
    username = username.split("?")[0]  # strip query params

    # Verify the account exists on Instagram
    async with ctx.typing():
        try:
            profile = await asyncio.to_thread(
                instaloader.Profile.from_username, L.context, username
            )
        except instaloader.exceptions.ProfileNotExistsException:
            await ctx.send(
                f"🦇 mochi looked everywhere but couldn't find `@{username}` on Instagram... "
                f"are you sure that's right? 👀"
            )
            return
        except Exception as e:
            await ctx.send(
                f"🦇 mochi ran into a problem checking that account! "
                f"Try again in a bit~ (error: `{e}`)"
            )
            return

    # Save to DB
    conn = db_connect()
    try:
        # Get most recent post ID so we don't spam old posts on first run
        last_id = None
        try:
            posts = profile.get_posts()
            first = next(iter(posts), None)
            if first:
                last_id = str(first.shortcode)
        except:
            pass

        conn.execute(
            """INSERT OR REPLACE INTO registrations
               (discord_id, discord_name, instagram, last_post_id, added_at)
               VALUES (?, ?, ?, ?, ?)""",
            (str(ctx.author.id), str(ctx.author), username, last_id,
             datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
    finally:
        conn.close()

    embed = discord.Embed(
        title="🍡 account linked!",
        description=(
            f"mochi will now watch **@{username}** for new posts and share them "
            f"in the art feed!\n\n"
            f"[visit profile](https://instagram.com/{username})"
        ),
        color=0xc084fc
    )
    embed.set_thumbnail(url=profile.profile_pic_url)
    embed.set_footer(text=f"linked by {ctx.author} • mochi bot 🦇")

    # Warn if no art channel has been set yet
    if get_art_channel(ctx.guild.id) is None:
        embed.add_field(
            name="⚠️ heads up!",
            value="no art feed channel is set yet! an admin needs to run `m!setchannel #channel` before mochi can post~",
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name="remove")
async def remove_account(ctx, link: str = None):
    """m!remove <instagram_link_or_username> — unregister your Instagram"""
    if link is None:
        await ctx.send("🦇 tell mochi which account to remove! `m!remove username`")
        return

    username = link.strip("/").split("/")[-1].replace("@", "").lower()

    conn = db_connect()
    cur = conn.execute(
        "DELETE FROM registrations WHERE discord_id=? AND instagram=?",
        (str(ctx.author.id), username)
    )
    conn.commit()
    conn.close()

    if cur.rowcount:
        await ctx.send(f"🦇 okay! mochi will stop watching **@{username}** for you~ 💜")
    else:
        await ctx.send(f"🦇 mochi doesn't have `@{username}` linked to your account!")


@bot.command(name="list")
async def list_accounts(ctx):
    """m!list — see all your linked accounts"""
    conn = db_connect()
    rows = conn.execute(
        "SELECT instagram, added_at FROM registrations WHERE discord_id=?",
        (str(ctx.author.id),)
    ).fetchall()
    conn.close()

    if not rows:
        await ctx.send(
            "🦇 you haven't linked any accounts yet!\n"
            "Use `m!add <instagram_link>` to get started~"
        )
        return

    lines = "\n".join(f"• [@{r[0]}](https://instagram.com/{r[0]})" for r in rows)
    embed = discord.Embed(
        title="🍡 your linked accounts",
        description=lines,
        color=0xc084fc
    )
    embed.set_footer(text="mochi is watching these for new posts 🦇")
    await ctx.send(embed=embed)


@bot.command(name="help")
async def help_command(ctx):
    """m!help — show all commands"""
    embed = discord.Embed(
        title="🦇 hi!! i'm mochi!!",
        description=(
            "i'm a cutesy bat who watches your art accounts and shares your posts "
            "here so everyone can see your work!! 🍡✨\n\n"
            "here's what i can do right now~"
        ),
        color=0xc084fc
    )
    embed.add_field(
        name="🎨 art commands",
        value=(
            "`m!add <instagram_link>` — link your instagram so mochi watches it!\n"
            "`m!remove <instagram_link>` — unlink an account\n"
            "`m!list` — see all your linked accounts\n"
            "`m!channel` — see where mochi is posting art"
        ),
        inline=False
    )
    embed.add_field(
        name="🔧 admin commands",
        value=(
            "`m!setchannel #channel` — set where mochi posts art *(requires Manage Channels)*\n"
            "`m!setchannel` — use the current channel as the art feed"
        ),
        inline=False
    )
    embed.add_field(
        name="🦇 other",
        value="`m!ping` — check if mochi is awake",
        inline=False
    )
    embed.set_footer(text="mochi bot • made with 💜 for the art server")
    await ctx.send(embed=embed)


@bot.command(name="ping")
async def ping(ctx):
    ms = round(bot.latency * 1000)
    await ctx.send(f"🦇 *flaps wings* mochi is awake!! pong~ `{ms}ms` 💜")


@bot.command(name="setchannel")
@commands.has_permissions(manage_channels=True)
async def set_channel(ctx, channel: discord.TextChannel = None):
    """m!setchannel #channel — (admin) set where Mochi posts art"""
    # If no channel mentioned, default to the current channel
    target = channel or ctx.channel

    set_art_channel(ctx.guild.id, target.id)

    embed = discord.Embed(
        title="🍡 art feed channel set!",
        description=(
            f"mochi will now post new artwork in {target.mention}! 🦇\n\n"
            f"make sure mochi has permission to **send messages** and "
            f"**embed links** in that channel~"
        ),
        color=0xc084fc
    )
    embed.set_footer(text=f"set by {ctx.author} • mochi bot 🦇")
    await ctx.send(embed=embed)

@set_channel.error
async def set_channel_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🦇 only admins with **Manage Channels** permission can set the art feed channel!")
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send("🦇 mochi couldn't find that channel! try mentioning it like `#art-feed`~")


@bot.command(name="channel")
async def show_channel(ctx):
    """m!channel — show the current art feed channel"""
    channel_id = get_art_channel(ctx.guild.id)
    if channel_id is None:
        await ctx.send(
            "🦇 no art feed channel set yet!\n"
            "admins can use `m!setchannel #channel-name` to set one~"
        )
        return
    channel = bot.get_channel(channel_id)
    if channel:
        await ctx.send(f"🍡 mochi is posting art in {channel.mention}! 🦇")
    else:
        await ctx.send(
            "🦇 mochi has a channel saved but can't find it anymore... "
            "an admin might need to run `m!setchannel` again!"
        )


# ── Background task: poll Instagram for new posts ─────────────────────────────

@tasks.loop(minutes=CHECK_EVERY)
async def check_instagram():
    conn = db_connect()
    rows = conn.execute(
        "SELECT discord_id, discord_name, instagram, last_post_id FROM registrations"
    ).fetchall()
    conn.close()

    # Group users by guild so we can look up the right art channel per server
    # We store guild_id in registrations — need to fetch it. For now we check all guilds.
    # Fetch guild→channel mapping
    conn = db_connect()
    guild_channels = {
        row[0]: int(row[1])
        for row in conn.execute("SELECT guild_id, art_channel FROM guild_settings").fetchall()
    }
    conn.close()

    for discord_id, discord_name, username, last_post_id in rows:
        # Find which guild this user is in (check all guilds Mochi is in)
        channel = None
        for guild_id, channel_id in guild_channels.items():
            guild = bot.get_guild(int(guild_id))
            if guild and guild.get_member(int(discord_id)):
                channel = bot.get_channel(channel_id)
                break

        if channel is None:
            print(f"[mochi] ⚠️  no art channel found for user {discord_name} (@{username})")
            continue

        try:
            profile = await asyncio.to_thread(
                instaloader.Profile.from_username, L.context, username
            )
            posts = profile.get_posts()
            new_posts = []

            for post in posts:
                if str(post.shortcode) == last_post_id:
                    break
                new_posts.append(post)
                if len(new_posts) >= 5:  # cap to avoid spam on first run
                    break

            if not new_posts:
                continue

            # Update last seen post
            conn = db_connect()
            conn.execute(
                "UPDATE registrations SET last_post_id=? WHERE discord_id=? AND instagram=?",
                (str(new_posts[0].shortcode), discord_id, username)
            )
            conn.commit()
            conn.close()

            # Post newest-first (reverse so timeline order)
            for post in reversed(new_posts):
                await post_to_channel(channel, profile, post, discord_id)
                await asyncio.sleep(2)  # small delay between posts

        except Exception as e:
            print(f"[mochi] error checking @{username}: {e}")
        
        await asyncio.sleep(5)  # be polite between users


async def post_to_channel(channel, profile, post, discord_id):
    """Build and send the Mochi art embed to the channel."""
    username = profile.username
    post_url = f"https://www.instagram.com/p/{post.shortcode}/"

    # Caption (truncated)
    caption = post.caption or ""
    if len(caption) > 300:
        caption = caption[:297] + "..."

    # Mochi intro message
    intro = mochi_intro(username)
    outro = mochi_caption()

    # Get image URL (first image for carousels)
    image_url = None
    try:
        if post.typename == "GraphSidecar":
            # carousel — grab first node
            node = next(iter(post.get_sidecar_nodes()))
            image_url = node.display_url
        else:
            image_url = post.url
    except:
        image_url = post.url

    embed = discord.Embed(
        description=f"*{caption}*" if caption else "",
        color=0xc084fc,
        url=post_url,
        timestamp=post.date_utc
    )
    embed.set_author(
        name=f"@{username}",
        url=f"https://instagram.com/{username}",
        icon_url=profile.profile_pic_url
    )
    embed.set_image(url=image_url)
    embed.add_field(name="", value=f"[view on instagram ↗]({post_url})", inline=False)
    embed.set_footer(text=f"{outro}  •  🦇 mochi bot")

    await channel.send(
        content=f"{intro}\n<@{discord_id}>",
        embed=embed
    )


@check_instagram.before_loop
async def before_check():
    await bot.wait_until_ready()
    print("[mochi] 🦇 starting instagram watcher~")


# ── Startup ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"[mochi] 🦇 logged in as {bot.user} (ID: {bot.user.id})")
    print(f"[mochi] 🍡 serving {len(bot.guilds)} server(s)")
    check_instagram.start()

bot.run(TOKEN)
