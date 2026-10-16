"""Champion decisions. main.py dispatches here after the draft."""
import struct
from randomness import below

import cambc
from cambc import game_map

Team, Item = cambc.Team, cambc.ItemType


def distance(a, b):
    return a.chebyshev_distance(b)


def tiles_around(position, radius):
    tiles = cambc.Bitboard()
    tiles.draw_chebyshev(position, radius)
    return tiles


def blocked_tiles():
    # Combine terrain and visible occupants using native bitboard operations.
    blocked = (game_map.walls() | game_map.holes() | game_map.altars()
               | game_map.spawn_region(Team.ENEMY) | cambc.vision.champion_tiles()
               | cambc.vision.camp_tiles() | cambc.vision.teleport_tiles())
    blocked.set(cambc.me().position(), False)
    return blocked

def move_towards_closest(goals):
    me = cambc.me()
    origin = me.position()

    if not me.can_move():
        print("MOVE DEBUG: cannot move")
        return False

    if goals.is_set(origin):
        print("MOVE DEBUG: already on a goal")
        return False

    blocked = blocked_tiles()
    goals &= ~blocked | cambc.vision.camp_tiles()

    if goals.is_empty():
        print("MOVE DEBUG: no goals left after filtering")
        return False

    if goals.count() == 1 and not blocked.is_set(goals.positions()[0]):
        result = me.move_towards(goals.positions()[0])
        print("MOVE DEBUG: direct move", result)
        return result

    field = cambc.DistanceField()
    field.compute_to(blocked & ~goals, goals, tiles_around(origin, 0), cambc.Bitboard())

    reachable = blocked.reachable_tiles(origin, me.base_stats().base_move_speed)
    candidates = [origin, *reachable.positions()]
    step = min(candidates, key=field.get)

    print(
        "MOVE DEBUG:",
        "goals =", goals.count(),
        "reachable =", reachable.count(),
        "origin distance =", field.get(origin),
        "step distance =", field.get(step),
        "step =", step,
        "origin =", origin,
        "step is reachable =", reachable.is_set(step),
    )

    if step == origin or field.get(step) >= field.get(origin):
        print("MOVE DEBUG: no improving step")
        return False

    result = me.move_absolute(step)
    print("MOVE DEBUG: move_absolute result =", result)
    return result

def attack_if_in_range(target):
    # Make one basic attack if the target is already in attack range.
    me = cambc.me()
    if (not me.can_attack() or not target.is_visible() or target.health() <= 0
            or not me.attack_tiles().is_set(target.position())):
        return False
    me.attack(target)
    return True

def farm_camps():
    # Attack a camp already in range, otherwise move toward the nearest camp tiles.
    for camp in cambc.vision.camps():
        if attack_if_in_range(camp):
            return

    # Union every group's spawn tiles except visibly respawning groups.
    goals = cambc.Bitboard()
    visible = cambc.vision.visible_tiles()
    for group in game_map.camp_groups():
        if (not (group.spawn_tiles() & visible).is_empty()
                and isinstance(group.state(), game_map.CampGroupRespawning)):
            continue
        goals |= group.spawn_tiles()

    # Fresh vision after movement may reveal a camp already in range.
    if move_towards_closest(goals):
        for camp in cambc.vision.camps():
            if attack_if_in_range(camp):
                return


class Bot:
    def __init__(self):
        # Per-champion state survives between turns. Pick one stat and keep buying it.
        self.chosen_stat = None

    def buy_items(self):
        # Spend only on power shards of the randomly chosen stat.
        me = cambc.me()
        item = (Item.POWER_SHARD_OF_STRENGTH, Item.POWER_SHARD_OF_FOCUS,
                Item.POWER_SHARD_OF_HEALTH)[self.chosen_stat]
        count = me.gold_count() // item.cost()
        if count and me.can_buy(item, count):
            me.buy(item, count)

    def play_turn(self):
        # Choose my champion's stat once.
        if self.chosen_stat is None:
            self.chosen_stat = 0

        me = cambc.me()

        if (
            not me.is_alive()
            or me.is_recalling()
            or me.is_submitting_gems()
            or me.is_teleporting()
            or (not me.can_move() and not me.can_attack())
        ):
            return

        me.set_priority(1 + below(100)) 

        at_spawn = game_map.spawn_region(Team.ALLY).is_set(me.position())

        # Buy items while at spawn.
        if at_spawn:
            self.buy_items()

        # First, bank gems if an unlocked altar is in range.
        if me.gem_count() > 0:
            for altar in game_map.altars().positions():
                if cambc.vision.has_altar_lock(altar):
                    continue

                if distance(me.position(), altar) <= cambc.constants.SUBMIT_GEMS_RANGE:
                    me.submit_gems(altar)
                    return

        # Carrying gems: submit if possible, otherwise pursue an unlocked altar.
        if me.gem_count() > 0:
            goals = cambc.Bitboard()

            for altar in game_map.altars().positions():
                if cambc.vision.has_altar_lock(altar):
                    continue

                if distance(me.position(), altar) <= cambc.constants.SUBMIT_GEMS_RANGE:
                    me.submit_gems(altar)
                    return

                goals |= tiles_around(
                    altar, cambc.constants.SUBMIT_GEMS_RANGE
                )

            if not goals.is_empty():
                move_towards_closest(goals)

            return  # Do not switch to combat or farming while carrying gems.

        # Recall when critically hurt and away from spawn.
        if not at_spawn and me.health() < me.max_health() * 0.35:
            me.recall()
            return

        # Attack an enemy champion if one is in range.
        for enemy in cambc.vision.champions(Team.ENEMY):
            if attack_if_in_range(enemy):
                return

        farm_camps()

        print(
            "round", cambc.round_number(),
            "pos", me.position(),
            "gems", me.gem_count(),
            "health", me.health()
        )



