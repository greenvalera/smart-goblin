from decimal import Decimal

from src.core.analyzer import DeckAnalyzer
from src.core.deck import CardInfo, Deck
from src.core.lands import recommend_deck_lands
from src.reports.models import DeckReport
from src.reports.telegram import TelegramRenderer


def test_complete_deck_counts_spell_copies_and_existing_nonbasic():
    deck = Deck(main_deck=['White Spell'] * 15 + ['Blue Spell'] * 8 +
                ['Plains'] * 8 + ['Island'] * 8 + ['Dual Land'], sideboard=['Green Spell'])
    infos = [
        CardInfo('White Spell', mana_cost='{W}', type_line='Creature'),
        CardInfo('Blue Spell', mana_cost='{U}', type_line='Instant'),
        CardInfo('Green Spell', mana_cost='{G}', type_line='Creature'),
        CardInfo('Dual Land', type_line='Land'),
    ]
    rec = recommend_deck_lands(deck, infos)
    assert rec.total_lands == 17 and rec.non_basic_count == 1
    assert rec.total_spells == 23
    assert sum(rec.lands.values()) == 16
    assert rec.lands['W'] > rec.lands['U']
    assert 'G' not in rec.lands
    # The same spells without the 16 visible basics must get the same target.
    deck.main_deck = [n for n in deck.main_deck if n not in {'Plains', 'Island'}]
    assert recommend_deck_lands(deck, infos) == rec


def test_duplicate_nonbasic_lands_are_counted_individually():
    deck = Deck(main_deck=['Spell'] * 23 + ['Dual Land'] * 2)
    rec = recommend_deck_lands(deck, [CardInfo('Spell', mana_cost='{U}'), CardInfo('Dual Land', type_line='Land')])
    assert rec.non_basic_count == 2 and rec.lands == {'U': 15}


def test_basics_do_not_change_scores_and_lands_are_not_zero_cost_spells():
    infos = [CardInfo('Spell', mana_cost='{U}', cmc=Decimal(1), colors=['U'], type_line='Instant',
                      rating=Decimal(2), win_rate=Decimal(56), games_played=1000),
             CardInfo('Land', cmc=Decimal(0), colors=[], type_line='Land')]
    analyzer = DeckAnalyzer()
    spells_only = analyzer.analyze(Deck(main_deck=['Spell'] * 23), infos)
    with_basics = analyzer.analyze(Deck(main_deck=['Spell'] * 23 + ['Island'] * 17), infos)
    assert with_basics.score == spells_only.score
    assert with_basics.estimated_win_rate == spells_only.estimated_win_rate
    with_nonbasic = analyzer.analyze(Deck(main_deck=['Spell'] * 23 + ['Island'] * 16 + ['Land']), infos)
    assert with_nonbasic.mana_curve == {1: 23}
    assert with_nonbasic.color_distribution == {'U': 100.0}


def test_multicolor_percentages_share_one_card_and_unknown_is_not_colorless():
    deck = Deck(main_deck=['Gold', 'Blue', 'Unknown', 'Plains'])
    infos = [CardInfo('Gold', colors=['W', 'U']), CardInfo('Blue', colors=['U'])]
    analysis = DeckAnalyzer().analyze(deck, infos)
    assert analysis.color_distribution == {'U': 75.0, 'W': 25.0}
    assert analysis.mana_curve == {}


def test_basic_lands_stay_visible_without_missing_rating_warning():
    deck = Deck(main_deck=['Island'] * 7 + ['Unknown Spell'])
    analysis = DeckAnalyzer().analyze(deck, [])
    report = DeckReport.build(deck, [], analysis)
    assert [c.name for c in report.unrated_cards] == ['Unknown Spell']
    output = TelegramRenderer().render(report)
    assert '🏔 Island x7' in output
    assert 'Island x7 — без даних' not in output
    assert 'Без оцінки:* Unknown Spell' in output
