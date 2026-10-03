import agent
import server


def test_versiones_definidas():
    assert agent.__version__
    assert server.__version__
