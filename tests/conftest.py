def pytest_addoption(parser):
    parser.addoption(
        "--update-golden", action="store_true", default=False,
        help="Rewrite the contract golden files and JSON Schemas from the current code, then pass",
    )
