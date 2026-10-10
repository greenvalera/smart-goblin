"""Exercise the actual report pipelines with Vision returning no set."""
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.bot import set_data
from src.bot.handlers import analyze, draft
from src.core import set_resolver
from src.db.models import Analysis, Set
from src.db.repository import CardData, CardRepository, RatingData, SetRepository, UserRepository


@pytest.mark.parametrize('route', ['draft', 'analyze'])
@pytest.mark.parametrize('case', ['known', 'unresolved', 'no_ratings', 'new_set'])
async def test_missing_set_never_saves_unrated_default_report(clean_session, monkeypatch, route, case):
    session = clean_session
    @asynccontextmanager
    async def use_session():
        yield session
    for module in [draft, analyze, set_data, set_resolver]:
        monkeypatch.setattr(module, 'get_session', use_session)

    user, _ = await UserRepository(session).get_or_create(12345)
    names = ['Campus Crier', 'Ajani Unrelenting', 'Blossom-Blessed Angel']
    async def seed():
        await SetRepository(session).get_or_create('FRA', 'Reality Fracture')
        repo = CardRepository(session)
        await repo.upsert_cards([
            CardData(name=names[0], set_code='FRA', cmc=Decimal('2'), colors=['W'], type_line='Creature'),
            CardData(name=names[1], set_code='FRA', cmc=Decimal('6'), colors=['R'], type_line='Planeswalker'),
            CardData(name=names[2] + ' // Seed Suture', set_code='FRA', cmc=Decimal('4'), colors=['W'], type_line='Creature'),
        ])
        if case != 'no_ratings':
            await repo.upsert_ratings([
                RatingData(card_name=n, set_code='FRA', source='17lands', rating=Decimal('4.5'),
                           win_rate=Decimal('62'), games_played=1000, format='PremierDraft')
                for n in names
            ])
    if case != 'new_set':
        await seed()
    else:
        # Real import boundary: create cards only after inference discovers the absent set.
        async def import_new(code):
            assert code == 'FRA'
            await seed()
            from src.parsers.set_importer import SetImportResult
            return SetImportResult(code, 'Reality Fracture', True, 3, 3)
        monkeypatch.setattr(set_data, 'import_set', import_new)

    if case == 'unresolved':
        names = ['Unrecognized A', 'Unrecognized B', 'Unrecognized C']
    monkeypatch.setattr(set_resolver.ScryfallParser, 'fetch_card_sets', AsyncMock(
        return_value={'FRA'} if case == 'new_set' else set()
    ))
    monkeypatch.setattr(set_resolver.ScryfallParser, 'close', AsyncMock())
    if case == 'no_ratings':
        monkeypatch.setattr(set_data, 'import_set', AsyncMock(return_value=None))
    message = AsyncMock()
    main = names + ['Plains'] * 6
    if route == 'draft':
        await draft._build_and_send_report(user, main, [], None, message)
    else:
        await analyze._run_deck_pipeline(AsyncMock(), message, user, main, [], None)

    saved = list((await session.scalars(select(Analysis))).all())
    output = message.edit_text.call_args.args[0]
    if case in {'known', 'new_set'}:
        assert len(saved) == 1
        assert (await session.get(Set, saved[0].set_id)).code == 'FRA'
        assert 'Reality Fracture' in output and 'Ajani Unrelenting' in output
        assert 'Blossom-Blessed Angel — без даних' not in output
        assert saved[0].total_score != Decimal('3.00')
    else:
        assert saved == []
        assert '3.0/5.0' not in output and '~50%' not in output


@pytest.mark.parametrize('route', ['draft', 'analyze'])
async def test_explicit_set_with_zero_rated_cards_cannot_save_report(clean_session, monkeypatch, route):
    @asynccontextmanager
    async def use_session():
        yield clean_session
    for module in [draft, analyze]:
        monkeypatch.setattr(module, 'get_session', use_session)
    user, _ = await UserRepository(clean_session).get_or_create(12345)
    await SetRepository(clean_session).get_or_create('HOB')
    message = AsyncMock()
    if route == 'draft':
        await draft._build_and_send_report(user, ['Missing Card'] * 40, [], 'HOB', message)
    else:
        await analyze._run_deck_pipeline(AsyncMock(), message, user, ['Missing Card'] * 40, [], 'HOB')
    assert list((await clean_session.scalars(select(Analysis))).all()) == []
    assert 'WR поки недоступні' in message.edit_text.call_args.args[0]
