"""What the reader types is checked before anything is charged or drawn: the name must be a real-sounding name,
and nothing unkind or inappropriate is printed in About Me."""
import asyncio

import pytest

from app.book import about_check
from app.book.about_check import Problem, rule_check


@pytest.mark.parametrize("name", ["Sarah", "Daniel", "Xiomara", "Oluwaseun", "Mei", "JJ", "Ana-Lucía", "Zoë",
                                  "Mary Kate", "Cassandra", "Dickens"])
def test_real_names_pass(name):
    assert rule_check({"name": name}) is None


@pytest.mark.parametrize("name", ["Stupid", "poopyhead", "Fatso", "12345", "!!!", "www.example.com",
                                  "my name is not important to you at all", "Idiot Face"])
def test_insults_and_non_names_are_refused(name):
    problem = rule_check({"name": name})
    assert problem and problem.field == "name" and "real first name" in problem.message


def test_a_rude_detail_names_its_field():
    problem = rule_check({"name": "Sam", "age": "7", "favourites": "butterflies, farther hikes",
                          "about": "My brother is a loser"})
    assert problem == Problem("about", problem.message) and "More about you" in problem.message


def test_without_a_model_only_the_rules_run(monkeypatch):
    async def must_not_ask(answers):
        raise AssertionError("asked OpenAI")
    monkeypatch.setattr(about_check, "_ask_openai", must_not_ask)
    assert asyncio.run(about_check.check({"name": "Sam"}, use_model=False)) is None


def test_the_model_judges_what_the_rules_miss(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    async def says_no(answers):
        assert answers == {"name": "Shrek", "age": "7"}  # blank answers aren't sent
        return Problem("name", about_check.message_for("name"))
    monkeypatch.setattr(about_check, "_ask_openai", says_no)
    assert asyncio.run(about_check.check({"name": "Shrek", "age": "7", "about": " "}, use_model=True)).field == "name"


def test_openai_down_does_not_stop_a_book(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    async def down(answers):
        raise TimeoutError
    monkeypatch.setattr(about_check, "_ask_openai", down)
    assert asyncio.run(about_check.check({"name": "Sam"}, use_model=True)) is None
