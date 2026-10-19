'''
ML controller: linear regression fitted with numpy from ml_dataset.csv
(same coefficients scikit-learn produced for the old ml_model.joblib).
'''

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

np = pytest.importorskip('numpy')


def test_coefficients_match_the_old_scikit_learn_model(monkeypatch):
	monkeypatch.chdir(ROOT)
	from controller.ml import LinearModel
	m = LinearModel()
	expected = [-0.00257213, 0.00531597, -0.02288929, -0.33180699]  # from ml_model.joblib (sklearn 1.7)
	assert np.allclose(m.coef, expected, atol=1e-6)
	assert m.predict([[200, 225, 0.5]]).shape == (1,)


def test_rate_of_change_starts_at_zero(monkeypatch):
	monkeypatch.chdir(ROOT)
	from controller.ml import Controller
	c = Controller({}, 'F', {'HoldCycleTime': 20})
	c.set_target(225)
	first = c.update(200)
	# with rate 0 the prediction is the plain linear model value
	assert first == pytest.approx(200 * -0.00257213 + 225 * 0.00531597 - 0.33180699, abs=1e-4)
