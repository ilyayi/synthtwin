"""Nanoparticle simulator for Au/Ag colloids (Turkevich/Frens, hot injection,
NaBH4, seeded growth, tannic-acid-assisted citrate).

model.predict / spectrum / calibrate are the entry points (load as
`--predictor synthtwin.lib.np.model` or `--model synthtwin.lib.np.model:make_model`).
Modules: params (parameter sets with sources), chemistry (recipe -> run, pH,
speciation), growth (nucleation/growth population balance), optics (Mie),
dls (z-average, PDI).
"""
