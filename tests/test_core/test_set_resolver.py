from unittest.mock import AsyncMock, patch

import pytest

from src.core.set_resolver import choose_set, infer_set_from_cards
from src.db.repository import CardData, CardRepository, SetRepository
from src.parsers.base import NetworkError
from src.parsers.scryfall import ScryfallParser


def test_duplicate_copies_and_ties_cannot_create_confidence():
    assert choose_set({'FRA': {'a', 'b', 'c'}, 'OLD': {'a', 'b', 'c'}}, 3) is None
    assert choose_set({'FRA': {'a', 'b', 'c'}}, 10) is None
    assert choose_set({'FRA': {'a', 'b', 'c', 'd'}, 'OLD': {'a', 'b'}}, 5) == 'FRA'


async def test_basics_and_repeated_single_card_do_not_infer():
    with patch('src.core.set_resolver.get_session') as session:
        assert await infer_set_from_cards(['Plains'] * 17 + ['Ajani'] * 4) is None
        session.assert_not_called()


async def test_existing_set_resolves_front_faces_and_bonus_sheets(clean_session):
    repo = CardRepository(clean_session)
    sets = SetRepository(clean_session)
    await sets.get_or_create('FRA')
    child, _ = await sets.get_or_create('BON')
    child.parent_set_code = 'FRA'
    await sets.get_or_create('OLD')
    await repo.upsert_cards([
        CardData(name='Campus Crier', set_code='FRA'),
        CardData(name='Blossom-Blessed Angel // Seed Suture', set_code='FRA'),
        CardData(name='Ajani Unrelenting', set_code='BON'),
        CardData(name='Campus Crier', set_code='OLD'),
    ])
    matches = await repo.get_set_matches(['campus crier', 'blossom-blessed angel', 'ajani unrelenting'])
    assert choose_set(matches, 3) == 'FRA'
    assert len(matches['FRA']) == 3


@pytest.mark.parametrize('remote_failure', [False, True])
async def test_unknown_set_uses_printings_not_latest_print(remote_failure):
    # DB behavior is covered by real PostgreSQL above; mock its service boundary here.
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def session():
        yield None
    with patch('src.core.set_resolver.get_session', session), \
         patch.object(CardRepository, 'get_set_matches', AsyncMock(return_value={})), \
         patch.object(ScryfallParser, 'fetch_card_sets', AsyncMock()) as fetch, \
         patch.object(ScryfallParser, 'close', AsyncMock()) as close:
        fetch.side_effect = NetworkError('offline') if remote_failure else [
            {'FRA', 'OLD'}, {'FRA'}, {'FRA'}, {'FRA', 'OTHER'}
        ]
        code = await infer_set_from_cards(['a', 'b', 'c', 'd'] + ['Plains'] * 17)
        assert code == (None if remote_failure else 'FRA')
        close.assert_awaited_once()


async def test_scryfall_printings_exclude_commander_and_deduplicate():
    parser = ScryfallParser()
    with patch.object(parser, '_request', AsyncMock(side_effect=[
        {'has_more': True, 'next_page': 'https://api.scryfall.com/next', 'data': [
            {'set': 'fra', 'set_type': 'expansion'},
            {'set': 'fra', 'set_type': 'expansion'},
            {'set': 'cmd', 'set_type': 'commander'},
        ]},
        {'has_more': False, 'data': [{'set': 'old', 'set_type': 'core'}]},
    ])) as request:
        assert await parser.fetch_card_sets('Card Name') == {'FRA', 'OLD'}
        assert 'unique=prints' in request.call_args_list[0].args[0]
