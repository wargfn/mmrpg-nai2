from marvel_mcp_narrator.core.character_state import Character, CharacterRoster

# 1. Create a character (e.g., Spider-Man archetype)
spidey = Character(
    name="Spider-Man",
    archetype="Striker",
    rank=4,
    melee=5,
    agility=6,
    resilience=4,
    vigilance=4,
    ego=3,
    logic=2
)

# 2. Check Defenses & Pools
print("Defenses:", spidey.get_defenses())      # Melee should be 15, Agility 16, etc.
print("Max Health:", spidey.max_health)          # 4 * 30 = 120
print("Current Focus:", spidey.current_focus)

# 3. Simulate Combat Damage
status = spidey.take_health_damage(35)
print("After 35 Damage:", status)                # Health should be 85, is_unconscious=False

# 4. Simulate a Critical Blow
status = spidey.take_health_damage(90)
print("After Lethal Hit:", status)               # Health <= 0, is_unconscious=True

