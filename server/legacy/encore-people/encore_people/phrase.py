"""A temporary password a person can read out or type from a message: four plain words and two digits, like `river-lamp-orange-slow-47`.

It is single-purpose: the person is asked to choose their own at the first sign-in (`mustChange`), and the owner sees it once. About 40 bits
(256 words, four of them, and two digits), made with the operating system's random source.
"""
from __future__ import annotations

import secrets

WORDS = (
    "able acorn alder amber anchor apple arrow aspen atlas autumn badge baker banjo barn basil beach beam bell berry birch bison blade "
    "bloom boat bolt book bread breeze brick bridge brook brush cabin cable cactus camel candle canoe canyon cape cargo cedar chair chalk "
    "charm cherry chess chime cider cliff clock cloud clover coast cobalt comet coral cotton crane creek crown daisy dawn delta desert "
    "dune eagle earth echo elbow ember fable falcon fawn feather fern ferry field finch flame flint flute forest fox frost garden gate "
    "ginger glade globe grain grape grove guitar harbor hazel heron hill honey hornet island ivory jade jelly jungle kettle kite lake "
    "lamp lantern lark laurel lemon lilac linen lotus lunar maple marble meadow melon mint mist moon moss mountain nectar nest noble "
    "oasis ocean olive onyx opal orange orchid otter oval paper pearl pebble pepper piano pine planet plum pond poppy prairie quail "
    "quartz quill rabbit rain raven reed ribbon ridge river robin rocket rose saddle sage sail sand scarlet sea shadow shell silver "
    "sketch slate slow snow solar sparrow spice spring spruce star stone storm stream summer sunny swan swift tango thistle thunder "
    "tiger timber topaz trail tulip tundra valley velvet violet walnut wave willow window winter wolf yarrow zebra zephyr zinc"
).split()


def temporary_password(words: int = 4) -> str:
    chosen = [secrets.choice(WORDS) for _ in range(words)]
    return "-".join(chosen) + f"-{secrets.randbelow(90) + 10}"
