# Chapter inputs

- `input.txt`: expanded introductory chapter on neuronal communication.
- `water_cycle.txt`: introductory chapter on reservoirs, transfers, groundwater,
  surface water, water budgets and human influences.
- `water_cycle_sample.txt`: shorter water-cycle input in three paragraphs, covering
  atmospheric transfers, infiltration and groundwater, runoff, storage and human
  influences. Select it with `--chapter water-cycle-simplified`; results save to
  `outputs/runs/water-cycle-simplified/<run-id>/`.
- `sample.txt`: preserved original 509-word neuroscience sample; select it with
  `--chapter neuroscience-simplified`. It uses the full pipeline and saves to
  `outputs/runs/neuroscience-simplified/<run-id>/`.

The expanded chapters are original explanatory prose for pipeline experiments,
not pasted research papers. Blank lines separate substantive paragraphs; there
are no title-only chunks. The two chapters run independently.

Background reading used to check terminology:

- [USGS Water Science School: water cycle](https://www.usgs.gov/water-science-school/water-cycle)
- [USGS: evapotranspiration](https://www.usgs.gov/water-science-school/science/evapotranspiration-and-water-cycle)
- [USGS: groundwater flow](https://www.usgs.gov/special-topics/water-science-school/science/groundwater-flow-and-water-cycle)
- [Neuroscience: chemical synapses](https://www.ncbi.nlm.nih.gov/books/NBK11009/)
- [Neuroscience: summation of synaptic potentials](https://www.ncbi.nlm.nih.gov/books/NBK11104/)
- [Molecular Biology of the Cell: ion channels and membrane properties](https://www.ncbi.nlm.nih.gov/books/NBK26910/)

These references document the input's educational context. They are not
automatically retrieved evidence for model-generated background edges.
