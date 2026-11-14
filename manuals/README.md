# Test manuals

Three public equipment manuals for developing and testing the RAG pipeline. They cover different equipment types and layouts: prose, cause/remedy tables, fault-code tables and maintenance grids.

| File | Equipment | Pages | Source |
|---|---|---|---|
| `grundfos_cr_cri_crn_pump.pdf` | Grundfos CR, CRI, CRN 1s-255 vertical multistage centrifugal pump: installation and operating instructions (English) | 59 | https://api.grundfos.com/literature/Grundfosliterature-6012970.pdf |
| `doosan_p250wjd_air_compressor.pdf` | Doosan Portable Power P250WJD-T3 diesel portable air compressor: operating and maintenance manual (Book 46553449 Rev A) | 64 | https://dealers.doosanportablepower.com/emea/documents/Parts/01.%20Portable%20Compressors/1.Small%20Range/USmade_P250_WJD/46553449-A-03-10-OM-P250WJD-T3.pdf |
| `lenze_smvector_vfd.pdf` | Lenze / AC Tech SMVector variable frequency drive: operating instructions (EDBSV571 EN 1.0) | 48 | https://captiveaire.com/CatalogContent/electriccontrols/doc/EDBSV751.pdf |

## Page numbering

The printed page number in the footer is not always the PDF page index. The citation logic needs to handle this.

- **Grundfos:** printed page = PDF page.
- **Doosan:** printed page = PDF page − 2.
- **Lenze:** printed page = PDF page − 2.

`test_questions.md` lists both numbers.

## Quirks worth knowing

- Doosan: the diagnostic code list on PDF p.40 says code **E** = "Generator switch ON", but the troubleshooting Table 16 on PDF p.60 lists it as **SECU CODE H**. Use this case to check that the assistant cites what each page actually says.
- Doosan maintenance schedule (PDF p.50) is a grid. Plain text extraction loses which column each mark is in. This is a good stress test for table chunking.
- Grundfos has "English (GB)" running headers on every page, and some pages extract as two columns.
