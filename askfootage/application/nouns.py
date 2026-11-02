"""Object nouns in plain English: check one, spell it one way, find them in a question.

A noun names a kind of object ("forklift", "traffic cone"), never a person's identity: nouns
about faces or identity are refused. The fixed vocabulary (askfootage.domain.vocabulary) is
only the set of nouns with a spelling of their own; any other noun in plain English is valid,
and reaches perception as typed. Reading a question for nouns is a deliberately simple
word-list rule, not language understanding: it can offer a noun the user did not mean, which
is why nothing is ever run (or spent) until the user confirms a noun by name.

Pure functions; no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from askfootage.application.errors import InvalidInputError
from askfootage.application.ingest_video import noun_problem
from askfootage.domain.vocabulary import UnknownNounError, interpret_text, lookup_noun

MAX_QUESTION_NOUNS = 4
"""Most nouns read from one question."""
MAX_PHRASE_WORDS = 3
"""Longest noun phrase read from a question, in words."""

SHAPE_RULE = "may only hold letters, digits, spaces, hyphens and apostrophes"
IDENTITY_RULE = "must name a kind of object, not a person's face or identity"

_SHAPE = re.compile(r"[^\W_]+(?:[ '\-][^\W_]+)*")
_TOKEN = re.compile(r"[^\W_]+(?:['\-][^\W_]+)*")
_ASCII_WORD = re.compile(r"[a-z]+")
_IDENTITY_WORDS = frozenset(
    "face faces facial fingerprint fingerprints identity biometric biometrics iris retina".split()
)

_STOP_WORDS = frozenset(
    """
    a an the this that these those some any every each all no none both either neither other
    another such me my mine you your we our us i it its he she him her his hers they them their
    theirs who whom whose which what when where why how of to in on at by for from with without
    within into onto over under above below near next beside behind between among around
    through across along past toward towards inside outside during before after until since
    about against up down off out and or but nor so than then if as while because also just
    only even still yet ever never again once is are was were be been being am do does did done
    doing have has had having will would shall should can could may might must get gets got
    getting show find see look search list give tell display watch check there here today
    yesterday tonight morning afternoon evening night day days hour hours minute minutes min
    mins second seconds sec secs time times week long longer more most less least many much few
    several first last ago footage video videos clip clips recording recordings camera cameras
    frame scene thing things stuff something anything everything nothing anyone anybody someone
    somebody everyone everybody nobody one ones lot lots kind sort number push pushes pushing
    pushed pull pulls pulling pulled lift lifts lifting lifted ride rides riding rode drive
    drives driving drove use uses using used wear wears wearing wore open opens opening opened
    close closes closing closed leave leaves leaving left arrive arrives arriving arrived come
    comes coming came go goes going went walk walks walking walked run runs running ran move
    moves moving moved pass passes passing passed take takes taking took bring brings bringing
    brought put puts putting place places placed drop drops dropping dropped pick picks picking
    picked park parks parking parked stop stops stopped stopping sit sits sitting sat appear
    appears appeared happen happens happened happening throw throws threw cross crosses
    crossing crossed seen seeing pic picture please
    """.split()
)
_PLACE_WORDS = frozenset(
    "in on at by from inside outside near beside behind between around through across along "
    "within under over above below into onto toward towards".split()
)


def canonical_noun(text: str) -> str:
    """The noun in its one spelling: lower case, single spaces, vocabulary synonyms resolved.

    "Boxes" and "box" both give "cardboard box" and "People" gives "person"; "cardboard BOX" is
    "cardboard box". Any other text is only lower-cased and tidied: "Forklift " is "forklift".
    """
    normal = " ".join(text.casefold().split())
    try:
        return lookup_noun(normal).value
    except UnknownNounError:
        pass
    if _ASCII_WORD.fullmatch(normal):
        found = interpret_text(normal).nouns
        if len(found) == 1:
            return found[0].value
    return normal


def check_noun(text: str) -> str:
    """The canonical noun, or InvalidInputError (field noun) saying which rule it breaks.

    A noun is 1 to 40 characters once tidied, made of words of letters and digits joined by
    single spaces, hyphens or apostrophes, and does not name a face or an identity. The
    message never repeats the text.
    """
    noun = canonical_noun(text)
    problem = noun_problem(noun)
    if problem is None and _SHAPE.fullmatch(noun) is None:
        problem = SHAPE_RULE
    if problem is None and _IDENTITY_WORDS & set(noun.split()):
        problem = IDENTITY_RULE
    if problem is not None:
        raise InvalidInputError("noun", problem)
    return noun


def open_phrases(text: str, zone_names: Sequence[str] = ()) -> list[str]:
    """Noun phrases a question names that the vocabulary has no word for, in order.

    Words are dropped when they are small words, verbs of motion, time words, words of a zone
    name, or the vocabulary's own object and relation words. A run of the words left is a
    phrase, unless it follows a place word ("near the loading door") or describes a
    vocabulary noun ("red bag"). At most MAX_PHRASE_WORDS words (the last ones) are kept.
    """
    zone_words = {word for name in zone_names for word in _TOKEN.findall(name.casefold())}
    phrases: list[str] = []
    run: list[str] = []
    in_place = False
    for word in [*_TOKEN.findall(text.casefold()), ""]:
        reading = interpret_text(word) if _ASCII_WORD.fullmatch(word) else None
        is_vocabulary = reading is not None and bool(reading.nouns or reading.relation)
        if (
            word
            and not is_vocabulary
            and word not in _STOP_WORDS
            and word not in zone_words
            and word not in _IDENTITY_WORDS
            and len(word) >= 3
            and not word.isdigit()
        ):
            run.append(word)
            continue
        if run:
            describes_vocabulary = reading is not None and bool(reading.nouns)
            if not in_place and not describes_vocabulary:
                phrases.append(" ".join(run[-MAX_PHRASE_WORDS:]))
            run = []
            in_place = False
        if word in _PLACE_WORDS:
            in_place = True
    return list(dict.fromkeys(phrases))


def nouns_in_question(text: str, zone_names: Sequence[str] = ()) -> list[str]:
    """The valid object nouns a question names: the vocabulary's first, then other phrases.

    Each is canonical (see canonical_noun) and appears once; at most MAX_QUESTION_NOUNS.
    """
    found = [noun.value for noun in interpret_text(text).nouns]
    for phrase in open_phrases(text, zone_names):
        try:
            noun = check_noun(phrase)
        except InvalidInputError:
            continue
        if noun not in found:
            found.append(noun)
    return found[:MAX_QUESTION_NOUNS]
