#!/usr/bin/env python3

'''
*****************************************
 PiFire Machine Learning Controller
*****************************************

 Description: This object uses machine learning (with SKLearn) for maintaining
 temperature in the grill.

  Configuration Defaults: 
  "config": {
   }

*****************************************
'''

'''
Imported Libraries

Orange Pi fork: the model is an ordinary least-squares linear regression of
cycle_ratio on (current, setpoint, rate_change), fitted with numpy from
controller/ml_dataset.csv when the controller starts (191 rows: instant).
Upstream loaded a scikit-learn LinearRegression pickled in ml_model.joblib,
which ties the file to one scikit-learn version; the coefficients are the same.
'''
import time
import numpy as np
from controller.base import ControllerBase 

DATASET = './controller/ml_dataset.csv'


class LinearModel:
	''' Least-squares fit with intercept; predict() mirrors scikit-learn's '''
	def __init__(self, path=DATASET):
		data = np.loadtxt(path, delimiter=',', skiprows=1)
		features = np.c_[data[:, :3], np.ones(len(data))]
		self.coef, *_ = np.linalg.lstsq(features, data[:, 3], rcond=None)

	def predict(self, rows):
		rows = np.asarray(rows, dtype=float)
		return rows @ self.coef[:3] + self.coef[3]

'''
Class Definition
'''
class Controller(ControllerBase):
	def __init__(self, config, units, cycle_data):
		super().__init__(config, units, cycle_data)
		self.model = LinearModel()
		self.set_target(0.0)
		self.last_temp = -99
		self.last_time = time.time()
		self.cycle_time = cycle_data['HoldCycleTime']

	def update(self, current):
		if self.units == 'C':
			current = int(current * (9/5) + 32) # Celsius to Fahrenheit

		now = time.time()

		cycle_time = now - self.last_time

		self.last_time = now 

		if self.last_temp == -99:
			self.last_temp = current  # upstream compared (==) instead of assigning: huge first rate
			cycle_time = self.cycle_time

		rate_of_change = (current - self.last_temp) / max(cycle_time, 0.001)  # Rate of Change
		self.last_temp = current

		cycle_ratio = self.model.predict([[current, self.set_point, rate_of_change]])

		return cycle_ratio[0]

	def set_target(self, set_point):
		self.set_point = set_point
		if self.units == 'C':
			self.set_point = int(set_point * (9/5) + 32)  # Convert to Fahrenheit

