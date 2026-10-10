"""Regressions for unknown sets outside /draft and stale set overrides."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.filters import CommandObject

from src.bot import set_data
from src.bot.handlers import analyze, draft, stats
from src.bot.set_data import SetStatus, set_mismatch_text
from src.vision.recognizer import RecognitionResult
from tests.test_bot.test_analyze_photo_routing import (
    _make_message, _make_state, _make_db_user,
)

CARDS = ['Ajani Unrelenting', 'Campus Crier', 'Predictive Preparations']


@asynccontextmanager
async def fake_session():
    yield MagicMock()


@pytest.mark.parametrize('route', ['photo', 'analyze', 'draft'])
async def test_unknown_deck_set_loaded_before_analysis(route):
    message, state, user = _make_message(), _make_state(), _make_db_user()
    recognition = RecognitionResult(main_deck=CARDS, sideboard=[], detected_set='FRA')
    status = SetStatus(known_cards=CARDS, has_ratings=True, available=True, imported=True)
    module = draft if route == 'draft' else analyze
    loader = '_ensure_set_data' if route == 'draft' else 'ensure_set_data'
    with patch.object(module, 'CardRecognizer') as recognizer, \
         patch.object(module, loader, AsyncMock(return_value=status)) as load, \
         patch.object(analyze, '_run_deck_pipeline', AsyncMock()) as pipeline:
        recognizer.return_value.recognize_cards = AsyncMock(return_value=recognition)
        if route == 'draft':
            await draft.handle_draft_main_photo(message, user, state)
            assert state.update_data.call_args.kwargs['draft_set_code'] == 'FRA'
        elif route == 'analyze':
            await analyze._run_analysis(message, user, state)
            pipeline.assert_awaited_once()
        else:
            await analyze.handle_photo_without_command(message, user, state)
            pipeline.assert_awaited_once()
        load.assert_awaited_once_with('FRA', message.answer.return_value)


async def test_single_card_imports_missing_set_and_allows_missing_ratings():
    message, state, user = _make_message(), _make_state(), _make_db_user('FRA')
    repo = MagicMock()
    repo.get_card_names_by_set = AsyncMock(return_value=[])
    recognition = RecognitionResult(main_deck=CARDS[:1], sideboard=[], detected_set='FRA')
    status = SetStatus(known_cards=CARDS, available=True, has_ratings=False)
    with patch.object(analyze, 'get_session', fake_session), \
         patch.object(analyze, 'CardRepository', return_value=repo), \
         patch.object(analyze, 'CardRecognizer') as recognizer, \
         patch.object(analyze, 'ensure_set_data', AsyncMock(return_value=status)) as load, \
         patch.object(analyze, '_handle_single_card', AsyncMock()) as single, \
         patch('src.parsers.scryfall_variants.get_card_variants', AsyncMock(return_value=[])):
        recognizer.return_value.recognize_cards = AsyncMock(return_value=recognition)
        await analyze.handle_photo_without_command(message, user, state)
        load.assert_awaited_once()
        single.assert_awaited_once()
        assert single.call_args.args[2:4] == ('Ajani Unrelenting', 'FRA')


@pytest.mark.parametrize('route', ['photo', 'analyze', 'draft'])
async def test_stale_hob_override_does_not_produce_default_score(route):
    message, state, user = _make_message(), _make_state(), _make_db_user('HOB')
    hob = ['Bilbo', 'Gandalf', 'Smaug']
    repo = MagicMock()
    repo.get_card_names_by_set = AsyncMock(return_value=hob)
    recognition = RecognitionResult(main_deck=CARDS, sideboard=[], detected_set='FRA')
    status = SetStatus(known_cards=hob, available=True, has_ratings=True)
    module = draft if route == 'draft' else analyze
    loader = '_ensure_set_data' if route == 'draft' else 'ensure_set_data'
    with patch.object(module, 'CardRecognizer') as recognizer, \
         patch.object(module, loader, AsyncMock(return_value=status)), \
         patch.object(analyze, 'get_session', fake_session), \
         patch.object(analyze, 'CardRepository', return_value=repo), \
         patch.object(analyze, '_run_deck_pipeline', AsyncMock()) as pipeline:
        recognizer.return_value.recognize_cards = AsyncMock(return_value=recognition)
        if route == 'draft':
            await draft.handle_draft_main_photo(message, user, state)
            state.set_state.assert_not_awaited()
        elif route == 'analyze':
            await analyze._run_analysis(message, user, state)
        else:
            await analyze.handle_photo_without_command(message, user, state)
        pipeline.assert_not_awaited()
        assert '/set reset' in message.answer.return_value.edit_text.call_args.args[0]


@pytest.mark.parametrize('available', [True, False])
async def test_set_command_checks_data_before_persisting_choice(available):
    message, state, user = _make_message(), _make_state(), _make_db_user('HOB')
    status = SetStatus(known_cards=CARDS if available else [], available=available)
    repo = MagicMock()
    repo.update_active_set = AsyncMock()
    with patch.object(stats, 'ensure_set_data', AsyncMock(return_value=status)) as load, \
         patch.object(stats, 'get_session', fake_session), \
         patch.object(stats, 'UserRepository', return_value=repo):
        await stats.handle_set(message, CommandObject(command='set', args='fra'), state, user)
        load.assert_awaited_once_with('FRA', message.answer.return_value)
        if available:
            repo.update_active_set.assert_awaited_once_with(message.from_user.id, 'FRA')
            state.update_data.assert_awaited_once_with(set_override='FRA')
        else:
            repo.update_active_set.assert_not_awaited()
            state.update_data.assert_not_awaited()


async def test_missing_ratings_retried_without_hammering_upstream():
    set_data._rating_attempts.clear()
    repo = MagicMock()
    repo.has_ratings_for_set = AsyncMock(return_value=False)
    with patch.object(set_data, 'get_session', fake_session), \
         patch.object(set_data, 'CardRepository', return_value=repo), \
         patch.object(set_data, 'fetch_known_cards', AsyncMock(return_value=CARDS)), \
         patch.object(set_data, 'import_set', AsyncMock(return_value=MagicMock())) as importer:
        first = await set_data.ensure_set_data('fra', AsyncMock())
        second = await set_data.ensure_set_data('FRA', AsyncMock())
        importer.assert_awaited_once_with('FRA')
        assert first.available and second.available
        assert not first.has_ratings and not second.has_ratings
    set_data._rating_attempts.clear()


async def test_invalid_set_never_imported():
    with patch.object(set_data, 'import_set', AsyncMock()) as importer:
        assert not (await set_data.ensure_set_data('FRA_bad', AsyncMock())).available
        importer.assert_not_awaited()


async def test_rating_refresh_failure_preserves_available_card_metadata():
    set_data._rating_attempts.clear()
    repo = MagicMock()
    repo.has_ratings_for_set = AsyncMock(return_value=False)
    with patch.object(set_data, 'get_session', fake_session), \
         patch.object(set_data, 'CardRepository', return_value=repo), \
         patch.object(set_data, 'fetch_known_cards', AsyncMock(return_value=CARDS)), \
         patch.object(set_data, 'import_set', AsyncMock(side_effect=RuntimeError('timeout'))):
        status = await set_data.ensure_set_data('FRA', AsyncMock())
        assert status.available and status.known_cards == CARDS
        assert not status.has_ratings
    set_data._rating_attempts.clear()


def test_basic_lands_do_not_mask_a_wrong_set():
    assert set_mismatch_text(CARDS + ['Island'] * 17, ['Island', 'Smaug'], 'HOB')
    assert set_mismatch_text(CARDS + ['Island'] * 17, CARDS, 'FRA') is None
