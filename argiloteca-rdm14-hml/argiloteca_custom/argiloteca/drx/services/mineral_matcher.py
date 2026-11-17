"""Bundled existing WebMineral-compatible matcher; no network or Flask imports.

Pure functions preserved from the local classifier used for the prior snapshot.
Candidates remain non-confirmatory; scores are not phase fractions.
"""
import math
CU_KA1 = 1.54056
SOURCE_SHA256 = 'ca5b6af6ef318429c51a925cc972032cb6076c2f3cf02c964d740ec06483b68f'

EMBEDDED_REFERENCE = [{'mineral': 'Kaolinite', 'formula': 'Al2Si2O5(OH)4', 'group': 'Grupo caulinita-serpentina', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 7.15, 'i': 100}, {'d': 3.58, 'i': 80}, {'d': 2.56, 'i': 60}]}, {'mineral': 'Halloysite', 'formula': 'Al2Si2O5(OH)4', 'group': 'Grupo caulinita-serpentina', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 7.35, 'i': 100}, {'d': 4.43, 'i': 55}, {'d': 3.63, 'i': 70}]}, {'mineral': 'Illite', 'formula': 'K0.65Al2.0[Al0.65Si3.35O10](OH)2', 'group': 'Grupo ilita e micas relacionadas', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 10.0, 'i': 100}, {'d': 5.0, 'i': 40}, {'d': 3.33, 'i': 75}]}, {'mineral': 'Muscovite', 'formula': 'KAl2(AlSi3O10)(OH)2', 'group': 'Grupo das micas', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 9.95, 'i': 100}, {'d': 4.48, 'i': 60}, {'d': 3.34, 'i': 80}]}, {'mineral': 'Brammallite', 'formula': '(Na,H3O)(Al,Mg,Fe)2(Si,Al)4O10[(OH)2,(H2O)]', 'group': 'Grupo ilita e micas relacionadas', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 9.77, 'i': 100}, {'d': 3.17, 'i': 100}, {'d': 1.485, 'i': 100}]}, {'mineral': 'Chlorite', 'formula': '(Mg,Fe,Al)6(Si,Al)4O10(OH)8', 'group': 'Grupo das cloritas', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 14.2, 'i': 100}, {'d': 7.1, 'i': 60}, {'d': 3.54, 'i': 80}]}, {'mineral': 'Montmorillonite', 'formula': '(Na,Ca)0.33(Al,Mg)2Si4O10(OH)2.nH2O', 'group': 'Grupo esmectita', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 15.0, 'i': 100}, {'d': 4.5, 'i': 55}, {'d': 2.56, 'i': 45}]}, {'mineral': 'Nontronite', 'formula': 'Na0.3Fe2(Si,Al)4O10(OH)2.nH2O', 'group': 'Grupo esmectita', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 15.4, 'i': 100}, {'d': 4.56, 'i': 100}, {'d': 1.52, 'i': 100}]}, {'mineral': 'Hectorite', 'formula': 'Na0.3(Mg,Li)3Si4O10(OH)2', 'group': 'Grupo esmectita', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 15.8, 'i': 80}, {'d': 4.58, 'i': 100}, {'d': 1.53, 'i': 100}]}, {'mineral': 'Quartz', 'formula': 'SiO2', 'group': 'Silicatos - tectossilicatos', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 3.34, 'i': 100}, {'d': 4.26, 'i': 35}, {'d': 1.82, 'i': 25}]}, {'mineral': 'Albite', 'formula': 'NaAlSi3O8', 'group': 'Feldspatos', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 3.19, 'i': 100}, {'d': 3.78, 'i': 45}, {'d': 4.03, 'i': 40}]}, {'mineral': 'Calcite', 'formula': 'CaCO3', 'group': 'Carbonatos', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 3.03, 'i': 100}, {'d': 2.28, 'i': 18}, {'d': 2.09, 'i': 18}]}, {'mineral': 'Goethite', 'formula': 'FeO(OH)', 'group': 'Oxidos/hidroxidos de ferro', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 4.18, 'i': 100}, {'d': 2.69, 'i': 70}, {'d': 2.45, 'i': 50}]}, {'mineral': 'Hematite', 'formula': 'Fe2O3', 'group': 'Oxidos de ferro', 'source': 'embedded WebMineral-compatible d/I reference', 'lines': [{'d': 2.7, 'i': 100}, {'d': 2.52, 'i': 50}, {'d': 3.68, 'i': 40}]}]

def two_theta_to_d(two_theta, wavelength=CU_KA1):
    theta = math.radians(two_theta / 2.0)
    sine = math.sin(theta)
    if sine <= 0:
        return None
    return wavelength / (2.0 * sine)

def d_to_two_theta(d_spacing, wavelength=CU_KA1):
    if not d_spacing or d_spacing <= 0:
        return None
    value = wavelength / (2.0 * d_spacing)
    if value <= 0 or value > 1:
        return None
    return math.degrees(2.0 * math.asin(value))

def moving_average(values, window):
    if window <= 1 or len(values) < window:
        return [float(value) for value in values]
    half = window // 2
    smoothed = []
    for index in range(len(values)):
        start = max(0, index - half)
        end = min(len(values), index + half + 1)
        chunk = values[start:end]
        smoothed.append(sum(chunk) / len(chunk))
    return smoothed

def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return float(ordered[index])

def extract_peaks(two_theta, intensity, max_peaks=12, smooth_window=5, min_distance_deg=0.18, min_prominence_ratio=0.04):
    if len(two_theta) < 3 or len(two_theta) != len(intensity):
        return []
    smoothed = moving_average([float(value) for value in intensity], smooth_window)
    baseline = percentile(smoothed, 0.1)
    maximum = max(smoothed) if smoothed else 0.0
    amplitude = max(maximum - baseline, 1.0)
    threshold = baseline + amplitude * min_prominence_ratio
    candidates = []
    for index in range(1, len(smoothed) - 1):
        value = smoothed[index]
        if value < threshold:
            continue
        if value >= smoothed[index - 1] and value >= smoothed[index + 1]:
            d_spacing = two_theta_to_d(two_theta[index])
            if d_spacing:
                candidates.append({'two_theta': round(float(two_theta[index]), 5), 'd': round(float(d_spacing), 5), 'intensity': round(float(intensity[index]), 5), 'relative_intensity': round(100.0 * max(value - baseline, 0.0) / amplitude, 2), 'index': index})
    candidates.sort(key=lambda item: item['relative_intensity'], reverse=True)
    selected = []
    for peak in candidates:
        if any((abs(peak['two_theta'] - other['two_theta']) < min_distance_deg for other in selected)):
            continue
        selected.append(peak)
        if len(selected) >= max_peaks:
            break
    return selected

def normalize_reference_payload(payload, cache_path):
    """Normaliza cache local WebMineral e completa linhas conhecidas embutidas.

    O cache dos 81 termos pode conter entradas de vocabulário sem linhas d/I
    reconhecidas. Para nao perder a classificação já existente, esta função
    preserva as 81 entradas e injeta linhas embutidas quando o nome coincide.
    """
    embedded_by_name = {str(item.get('mineral') or '').casefold(): item for item in EMBEDDED_REFERENCE}
    records = []
    for row in payload.get('records') or []:
        item = dict(row)
        name = str(item.get('mineral') or item.get('title_en') or item.get('id') or '').strip()
        embedded = embedded_by_name.get(name.casefold())
        if embedded and (not item.get('lines')):
            item['lines'] = embedded.get('lines') or []
            item.setdefault('formula', embedded.get('formula'))
            item.setdefault('group', embedded.get('group'))
            item['source'] = item.get('source') or embedded.get('source')
            item['line_source'] = 'embedded WebMineral-compatible d/I reference merged into local vocabulary cache'
        records.append(item)
    existing = {str(item.get('mineral') or '').casefold() for item in records}
    for embedded in EMBEDDED_REFERENCE:
        if str(embedded.get('mineral') or '').casefold() not in existing:
            extra = dict(embedded)
            extra['status'] = 'embedded_extra'
            records.append(extra)
    normalized = dict(payload)
    normalized['records'] = records
    normalized['source'] = payload.get('source') or 'local_webmineral_cache'
    normalized['cache_path'] = str(cache_path)
    normalized['notes'] = (payload.get('notes') or []) + ['Cache local normalizado pelo classificador da Argiloteca.', 'Entradas sem linhas d/I podem ser complementadas pela referencia embutida quando houver correspondencia nominal.']
    return normalized

def match_reference(peaks, reference, tolerance_d=0.08, tolerance_two_theta=0.35, top=8):
    matches = []
    if not peaks:
        return matches
    peak_by_strength = sorted(peaks, key=lambda item: item['relative_intensity'], reverse=True)
    for entry in reference:
        line_matches = []
        weighted_score = 0.0
        total_weight = 0.0
        for line in entry.get('lines') or []:
            d_ref = float(line.get('d') or 0)
            i_ref = max(float(line.get('i') or 0), 1.0)
            two_theta_ref = d_to_two_theta(d_ref)
            if not d_ref or not two_theta_ref:
                continue
            total_weight += i_ref
            best = None
            for peak in peak_by_strength:
                delta_d = abs(float(peak['d']) - d_ref)
                delta_two_theta = abs(float(peak['two_theta']) - two_theta_ref)
                if delta_d <= tolerance_d or delta_two_theta <= tolerance_two_theta:
                    closeness_d = max(0.0, 1.0 - delta_d / max(tolerance_d, 0.0001))
                    closeness_t = max(0.0, 1.0 - delta_two_theta / max(tolerance_two_theta, 0.0001))
                    closeness = max(closeness_d, closeness_t)
                    candidate = {'reference_d': round(d_ref, 5), 'reference_two_theta': round(two_theta_ref, 5), 'reference_intensity': i_ref, 'observed_d': peak['d'], 'observed_two_theta': peak['two_theta'], 'observed_relative_intensity': peak['relative_intensity'], 'delta_d': round(delta_d, 5), 'delta_two_theta': round(delta_two_theta, 5), 'closeness': round(closeness, 4)}
                    if not best or candidate['closeness'] > best['closeness']:
                        best = candidate
            if best:
                line_matches.append(best)
                weighted_score += i_ref * best['closeness']
        if not total_weight:
            continue
        coverage = len(line_matches) / max(len(entry.get('lines') or []), 1)
        score = weighted_score / total_weight * (0.55 + 0.45 * coverage)
        if line_matches:
            matches.append({'mineral': entry.get('mineral'), 'formula': entry.get('formula'), 'group': entry.get('group'), 'source': entry.get('source'), 'score': round(score, 4), 'confidence': confidence_label(score, coverage, len(line_matches)), 'matched_lines': len(line_matches), 'reference_lines': len(entry.get('lines') or []), 'coverage': round(coverage, 4), 'matches': line_matches})
    matches.sort(key=lambda item: (item['score'], item['matched_lines']), reverse=True)
    return matches[:top]

def confidence_label(score, coverage, matched_lines):
    if score >= 0.72 and coverage >= 0.66 and (matched_lines >= 2):
        return 'alta'
    if score >= 0.45 and matched_lines >= 2:
        return 'media'
    return 'baixa'
