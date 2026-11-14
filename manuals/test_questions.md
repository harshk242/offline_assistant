# RAG test questions

Every expected answer was checked against the PDF text. Pages are shown as **PDF page / printed page**.

Categories:
- **direct:** the question uses the manual's own wording.
- **paraphrase:** the question uses technician wording that differs from the manual. This tests semantic retrieval.
- **code:** a fault-code lookup.
- **cross:** the question doesn't name a manual, so the assistant has to pick the right one.
- **refuse:** the manuals don't contain the answer. The assistant should say so and not guess.

## Grundfos CR pump (`grundfos_cr_cri_crn_pump.pdf`)

| # | Type | Question | Expected answer | Source |
|---|---|---|---|---|
| G1 | paraphrase | The pump won't start when I hit the switch. What should I check? | §10.1 "The motor does not run when started": power supply failure, blown fuses, tripped motor-protective circuit breaker, tripped thermal protection, faulty contacts or coil in the breaker, defective control circuit, defective motor. | p.35 / 35 |
| G2 | paraphrase | Pump is running but nothing's coming out. | §10.6 "The pump runs but gives no water": inlet pipe or pump blocked; foot or non-return valve stuck closed; leak in inlet pipe; air in inlet pipe or pump; motor turning the wrong way. | p.36 / 36 |
| G3 | direct | How do I reverse the direction of rotation if it's wrong? | Interchange two phases of the motor's power supply. The correct direction is shown by arrows on the motor fan cover. | p.26 / 26 |
| G4 | paraphrase | The breaker kicks out as soon as I power the pump on. | §10.2: blown fuse or tripped breaker, faulty breaker contacts, loose or faulty cable connection, defective motor winding, pump mechanically blocked, breaker overload setting too low. | p.35 / 35 |
| G5 | paraphrase | It's making a rattling or gravel noise. | §10.9 "unexpected noise": cavitation from too little inlet pressure, so check inlet conditions. Also an incorrect shaft position, or noise from a frequency converter (fit an output or sinusoidal filter). | p.36 / 36 |
| G6 | direct | How many times per hour can I start a pump with a 4 kW motor? | 100 starts per hour (for 3–4 kW MG or Innomotics motors). | p.40 / 40 |
| G7 | direct | How often should the motor bearings be replaced on a 5.5 kW 2-pole motor at 40 °C ambient? | Every 20,000 operating hours (1.1–7.5 kW at 40 °C). The interval is twice as long for 4-pole motors. | p.32 / 32 |
| G8 | paraphrase | Water is dripping from around the shaft. | §10.8 "leakage from the shaft seal": the seal is defective, so replace it. | p.36 / 36 |
| G9 | direct | What should I do before starting the pump for the first time? | Fill (prime) it with liquid, because dry running damages the bearings and shaft seal. Then start, check the direction of rotation, vent, and check the shaft seal for leaks during run-in. | p.25 / 25 |

## Doosan P250WJD compressor (`doosan_p250wjd_air_compressor.pdf`)

| # | Type | Question | Expected answer | Source |
|---|---|---|---|---|
| D1 | code | The compressor display is showing a 1. What does it mean? | SECU code 1: shutdown on high airend discharge temperature (248 °F / 120 °C). | p.40 / 38 |
| D2 | code | Code 5 on the compressor controller. | Shutdown on low engine oil pressure (12 psi / 0.83 bar). Causes (Table 8): low oil level, clogged oil filter, machine more than 15° out of level, wrong oil, faulty pressure switch, faulty SECU. | p.40 / 38, p.58 / 56 |
| D3 | paraphrase | The compressor keeps overheating and shutting itself off. What could cause that? | Table 4 (code 1) and Table 5 (code 2): dirty cooler, low compressor oil, clogged oil filters, operating pressure too high, recirculating cooling air, machine out of level, ambient above 120 °F, wrong oil, faulty bypass thermostat, loose belts, and others. | p.56–57 / 54–55 |
| D4 | paraphrase | Compressor won't fire up at all. | Table 3 "Machine Will Not Run": out of fuel, low fuel shutdown, high airend or separator temperature, low oil pressure, high coolant temperature, low battery, faulty sensor, engine fault, alternator, SECU. | p.56 / 54 |
| D5 | direct | When is the first engine oil change due? | Initial engine oil and filter change at 50 hours. | p.50 / 48 |
| D6 | code | What does code 3 mean? | Low battery voltage alert (below 11.6 VDC). The machine keeps running; it's an alert, not a shutdown. Remedy: measure, then charge or replace the battery; tighten cables; check belts and alternator. | p.40 / 38, p.57 / 55 |
| D7 | paraphrase | Engine bogging down and shutting off at low RPM. | Code 7 low engine speed (idle below 200 rpm), Table 10: clogged fuel filters, clogged air filter, pressure too high, faulty regulator, faulty separator element, and others. | p.40 / 38, p.58 / 56 |
| D8 | direct | Which items should be checked daily? | Compressor oil level, engine oil level, radiator coolant level, gauges and lamps, air cleaner service indicators, and others (maintenance schedule). | p.50 / 48 |

## Lenze SMVector VFD (`lenze_smvector_vfd.pdf`)

| # | Type | Question | Expected answer | Source |
|---|---|---|---|---|
| L1 | code | Drive is showing F.OF. | Output fault (transistor fault). Possible causes: output short circuit (check motor and cable), acceleration too short (increase P104/P125), severe motor overload, boost too high (lower P168/P169), cable capacitive charging current, failed output transistor. | p.45 / 43 |
| L2 | code | What's an HF fault and how do I fix it? | High DC bus voltage. Either mains voltage is too high (check mains and P107), or decel is too short or there's too much regen (increase P105/P126/P127 or add dynamic braking). | p.44 / 42 |
| L3 | paraphrase | The drive tripped because it lost a phase on the incoming power. | F.SF single-phase fault: a mains phase has been lost, so check mains voltage. | p.45 / 43 |
| L4 | code | The display says LC and the drive won't restart. | Fault lockout: 5 auto-restart attempts failed (P110 = 3–6). A manual reset is required. Check fault history (P500) and correct the fault. | p.42 / 40 |
| L5 | paraphrase | Drive faults the moment I power it on with the run switch already closed. | F.UF start fault: the start command was present at power-up (P110 = 0 or 2). Wait at least 2 s after power-up before starting, or change the start method (P110). | p.45 / 43 |
| L6 | paraphrase | Drive got too hot and tripped. | F.AF high temperature fault: reduce the load and improve cooling. | p.44 / 42 |
| L7 | direct | How do I see which device sent the stop command? | Press and hold Mode while stopped. The display alternates `L.stp`, `t.stp`, `r.stp` or `n.stp` (local keypad, terminal strip, remote keypad, network). | p.43 / 41 |
| L8 | paraphrase | Motor is tripping on ground fault. | F.OF1 output ground fault: grounded motor phase (check motor and cable), or excessive cable charging current (use shorter cables). | p.45 / 43 |

## Cross-manual and disambiguation

| # | Type | Question | Expected behaviour |
|---|---|---|---|
| X1 | cross | My unit has an overtemperature shutdown, what do I check? | This is ambiguous. Either ask which equipment, or give both the Doosan code 1/2/4 tables and the Lenze F.AF fault, with each source labelled. |
| X2 | cross | What does code 5 mean? | Doosan (low engine oil pressure). Lenze has no plain "5" code. |
| X3 | cross | Motor won't run. | Grundfos §10.1 is the strongest match. Lenze `stoP` or Doosan Table 3 are acceptable if they're cited. |

## Should refuse (not in the manuals)

| # | Question | Expected behaviour |
|---|---|---|
| R1 | What's the torque spec for the cylinder head bolts on the compressor engine? | Not in this manual (it points to the engine maker's docs). Say so; don't make up a number. |
| R2 | How do I reset an error on a Carrier rooftop unit? | No Carrier manual is loaded. Say so. |
| R3 | What is fault code F.OC on the SMVector? | No F.OC exists in the fault table (overcurrent shows as F.OF). Say the code isn't listed; F.OF is an optional pointer. |
| R4 | What's the part number for a replacement Grundfos shaft seal kit for a CR 32? | Part numbers aren't in this document. Say so. |
