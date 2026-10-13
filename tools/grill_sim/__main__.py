'''
Grill simulator command line.

  python -m tools.grill_sim                          # all scenarios, default controller
  python -m tools.grill_sim --controller pid_sp      # another controller
  python -m tools.grill_sim --compare pid pid_ac pid_sp pid_clamping
  python -m tools.grill_sim --plot sim.png           # also save a chart (needs matplotlib)
'''

import argparse
import json

from tools.grill_sim.harness import SimConfig
from tools.grill_sim import scenarios


def main():
	parser = argparse.ArgumentParser(description='PiFire grill simulator')
	parser.add_argument('--controller', default='pid')
	parser.add_argument('--compare', nargs='+', metavar='CONTROLLER', help='run every scenario for these controllers')
	parser.add_argument('--units', default='C', choices=['C', 'F'])
	parser.add_argument('--no-flameout-detect', action='store_true', help='original PiFire behaviour')
	parser.add_argument('--scenario', choices=list(scenarios.SCENARIOS), action='append')
	parser.add_argument('--plot', metavar='PNG')
	parser.add_argument('--json', action='store_true')
	args = parser.parse_args()

	controllers = args.compare or [args.controller]
	names = args.scenario or list(scenarios.SCENARIOS)
	results = {}
	for controller in controllers:
		for name in names:
			config = SimConfig(controller=controller, units=args.units, flameout_detect=not args.no_flameout_detect)
			metrics, result = scenarios.SCENARIOS[name](config)
			results[(controller, name)] = (metrics, result)

	if args.json:
		print(json.dumps({f'{c}/{n}': m for (c, n), (m, _) in results.items()}, indent=2))
	else:
		for (controller, name), (metrics, _) in results.items():
			print(f'{controller:24} {name:14} {json.dumps(metrics)}')

	if args.plot:
		import matplotlib
		matplotlib.use('Agg')
		import matplotlib.pyplot as plt
		fig, axes = plt.subplots(len(names), 1, figsize=(11, 3.2 * len(names)), squeeze=False)
		for row, name in enumerate(names):
			ax = axes[row][0]
			for controller in controllers:
				_, r = results[(controller, name)]
				ax.plot([t / 60 for t in r.t], r.temp_c, label=controller, linewidth=1.2)
			ax.set_title(name)
			ax.set_ylabel('C')
			ax.grid(alpha=0.3)
			ax.legend(loc='upper right', fontsize=8)
		axes[-1][0].set_xlabel('minuti')
		fig.tight_layout()
		fig.savefig(args.plot, dpi=90)
		print(f'Grafico salvato in {args.plot}')


if __name__ == '__main__':
	main()
