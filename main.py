import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import random
import os
import time

# ---------------- 기본 설정 ----------------
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

CATEGORY_ID = 1486640616753463369

# ---------------- DB ----------------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS money (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER,
    last_claim INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS channels (
    channel_id INTEGER PRIMARY KEY,
    owner_id INTEGER
)
""")

conn.commit()

# ---------------- 도박 버튼 ----------------
class GambleView(discord.ui.View):
    def __init__(self, user, amount, win_chance):
        super().__init__(timeout=30)
        self.user = user
        self.amount = amount
        self.win_chance = win_chance

    @discord.ui.button(label="👀 결과 확인하기", style=discord.ButtonStyle.primary)
    async def check_result(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user != self.user:
            return await interaction.response.send_message("본인만 가능", ephemeral=True)

        cursor.execute("SELECT balance FROM money WHERE user_id=?", (self.user.id,))
        result = cursor.fetchone()

        if not result:
            return await interaction.response.send_message("데이터 없음", ephemeral=True)

        balance = result[0]

        if random.random() < self.win_chance:
            balance += self.amount
            title = "🎉 도박 성공"
            result_text = f"🎯 +{self.amount:,}머니"
            color = discord.Color.green()
        else:
            balance -= self.amount
            title = "💀 도박 실패"
            result_text = f"💀 -{self.amount:,}머니"
            color = discord.Color.red()

        cursor.execute("UPDATE money SET balance=? WHERE user_id=?", (balance, self.user.id))
        conn.commit()

        embed = discord.Embed(
            title=title,
            description=f"🎲 확률: {int(self.win_chance*100)}%\n\n{result_text}\n\n💰 잔액: {balance:,}",
            color=color
        )

        await interaction.response.edit_message(embed=embed, view=None)

# ---------------- 보이스 생성 ----------------
class VoiceModal(discord.ui.Modal, title="보이스채널 생성"):
    name = discord.ui.TextInput(label="채널 이름", required=True)
    desc = discord.ui.TextInput(label="채널 설명", style=discord.TextStyle.paragraph, required=True)
    limit = discord.ui.TextInput(label="최대 인원", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        category = guild.get_channel(CATEGORY_ID)

        user_limit = int(self.limit.value) if self.limit.value.isdigit() else 0

        new_channel = await guild.create_voice_channel(
            name=self.name.value,
            category=category,
            user_limit=user_limit
        )

        cursor.execute("INSERT INTO channels VALUES (?, ?)", (new_channel.id, interaction.user.id))
        conn.commit()

        embed = discord.Embed(
            title="🎤 보이스 채널 생성됨",
            color=discord.Color.green()
        )
        embed.add_field(name="채널", value=new_channel.mention, inline=False)
        embed.add_field(name="설명", value=self.desc.value, inline=False)
        embed.add_field(name="생성자", value=interaction.user.mention, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

class VoiceView(discord.ui.View):
    @discord.ui.button(label="🎤 보이스채널 만들기", style=discord.ButtonStyle.primary)
    async def create_voice(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VoiceModal())

@bot.command()
@commands.has_permissions(administrator=True)
async def 버튼(ctx):
    embed = discord.Embed(
        title="🎤 보이스채널 생성",
        description=(
            "아래 버튼을 눌러서\n"
            "음성 채팅방을 생성할 수 있습니다.\n\n"
            "채널은 사람이 없으면 자동 삭제됩니다.\n\n"
            "원하는 설정을 입력해서 채널을 만들어보세요!"
        ),
        color=0x5865F2
    )
    await ctx.send(embed=embed, view=VoiceView())

# ---------------- 자동 삭제 ----------------
@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel:
        cursor.execute("SELECT owner_id FROM channels WHERE channel_id=?", (before.channel.id,))
        if cursor.fetchone() and len(before.channel.members) == 0:
            await before.channel.delete()
            cursor.execute("DELETE FROM channels WHERE channel_id=?", (before.channel.id,))
            conn.commit()

# ---------------- 돈 시스템 (24시간 지급) ----------------
@bot.tree.command(name="돈줘")
async def give_money(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = int(time.time())

    cursor.execute("SELECT balance, last_claim FROM money WHERE user_id=?", (user_id,))
    result = cursor.fetchone()

    if result:
        balance, last_claim = result

        if now - last_claim < 86400:
            remain = 86400 - (now - last_claim)
            hours = remain // 3600
            minutes = (remain % 3600) // 60

            return await interaction.response.send_message(
                f"⏳ 아직 못받음\n남은시간: {hours}시간 {minutes}분",
                ephemeral=True
            )

        balance += 10000
        cursor.execute(
            "UPDATE money SET balance=?, last_claim=? WHERE user_id=?",
            (balance, now, user_id)
        )

    else:
        cursor.execute(
            "INSERT INTO money VALUES (?, ?, ?)",
            (user_id, 10000, now)
        )

    conn.commit()

    embed = discord.Embed(
        title="💰 돈 지급",
        description="✅ 10,000머니 지급 완료",
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed)

# ---------------- 도박 ----------------
@bot.tree.command(name="도박")
@app_commands.describe(베팅="베팅 금액 입력")
async def gamble(interaction: discord.Interaction, 베팅: int):

    cursor.execute("SELECT balance FROM money WHERE user_id=?", (interaction.user.id,))
    result = cursor.fetchone()

    if not result:
        return await interaction.response.send_message("먼저 /돈줘", ephemeral=True)

    balance = result[0]

    if 베팅 <= 0 or 베팅 > balance:
        return await interaction.response.send_message("금액 오류", ephemeral=True)

    ratio = 베팅 / balance
    win_chance = 0.6 - (ratio * 0.5)
    win_chance = max(0.1, min(0.6, win_chance))

    embed = discord.Embed(
        title="🎰 도박 진행 중",
        description=f"🎲 확률: {int(win_chance*100)}%\n\n버튼 눌러 결과 확인",
        color=discord.Color.blue()
    )

    await interaction.response.send_message(
        embed=embed,
        view=GambleView(interaction.user, 베팅, win_chance)
    )

# ---------------- 방장 ----------------
def is_owner(user_id, channel_id):
    cursor.execute("SELECT owner_id FROM channels WHERE channel_id=?", (channel_id,))
    result = cursor.fetchone()
    return result and result[0] == user_id

@bot.tree.command(name="이름변경")
async def rename(interaction: discord.Interaction, 이름: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("음성 없음", ephemeral=True)

    channel = interaction.user.voice.channel
    if not is_owner(interaction.user.id, channel.id):
        return await interaction.response.send_message("방장만 가능", ephemeral=True)

    await channel.edit(name=이름)
    await interaction.response.send_message("완료", ephemeral=True)

# ---------------- 준비 ----------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} 준비 완료!")
    print("봇 완전히 실행됨")

# ---------------- 실행 ----------------
bot.run(os.getenv("BOT_TOKEN"))
