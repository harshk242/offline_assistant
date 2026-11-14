from assistant.search import Hit, match_expression, query_terms, search


def pages(hits):
    return [(h.manual, h.page) for h in hits]


def test_returns_hit_tuples_ranked_by_score(conn):
    hits = search("fuses blown", conn=conn)
    assert hits and isinstance(hits[0], Hit) and isinstance(hits[0], tuple)
    manual, page, heading, text, score = hits[0]
    assert (manual, page) == ("pump", 35) and score > 0
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_k_limits_results(conn):
    assert len(search("motor fault oil pump", k=2, conn=conn)) == 2


def test_stemming_matches_other_word_forms(conn):
    # Porter stemming: "running" ~ "runs", "replacing" ~ "Replace".
    assert ("pump", 36) in pages(search("pump running", conn=conn))
    assert ("pump", 35) in pages(search("replacing fuse", conn=conn))


def test_terms_are_ored_so_a_missing_word_does_not_empty_results(conn):
    hits = search("blown fuses xylophone", conn=conn)
    assert pages(hits)[0] == ("pump", 35)


def test_filler_words_are_dropped():
    assert query_terms("What should I check when the pump won't start?") == ["check", "pump", "start"]


def test_dotted_fault_code_is_a_phrase(conn):
    assert '"f of"' in match_expression("Drive is showing F.OF.")
    assert pages(search("Drive is showing F.OF.", conn=conn))[0] == ("vfd", 45)


def test_hyphenated_fault_code(conn):
    assert query_terms("What is E-204?") == ["e 204"]
    assert pages(search("What is E-204?", conn=conn)) == [("vfd", 46)]


def test_labelled_code_phrase_prefers_the_code_table(conn):
    assert "code 5" in query_terms("What does code 5 mean?")
    assert ("compressor", 58) == pages(search("What does code 5 mean?", conn=conn))[0]


def test_no_results(conn):
    assert search("carrier rooftop thermostat", conn=conn) == []
    assert search("what is the", conn=conn) == []  # only filler words
    assert search("", conn=conn) == []


def test_fts_syntax_in_question_is_neutralised(conn):
    # Operators and quotes must not raise sqlite errors.
    for q in ['pump AND NOT "motor', "heading:pump", "NEAR(pump motor)", "pump*", "(fuse"]:
        search(q, conn=conn)
