def test_returns_none_when_no_reference(tmp_path):
    import reference_judge

    reference_judge.DATASET_DIR = tmp_path
    (tmp_path / "case-x").mkdir()
    score, reason = reference_judge.judge(
        outputs={"case_dir": str(tmp_path / "case-x"), "files": {}}
    )
    assert score is None
    assert "reference" in reason.lower()
