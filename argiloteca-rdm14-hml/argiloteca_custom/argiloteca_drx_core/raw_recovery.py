"""Restricted recovery of documented layouts, without replacing original files.

Layout authorities: xylib Bruker reader (DIFFRAC-AT v1/v2, RAW1.01,
RAW4 coupled single-range); Profex Rigaku FI/BU; scattio Rigaku RAS;
GSAS manual ESD records.
No calibration, wavelength inference, phase identification or publication.
Legacy acquisition status and GSAS CW/TOF units cannot be established here.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import math
import re
import struct

from .parser_errors import (
    CurveParseError, CurveLimitExceededError, InvalidCurveHeaderError, InvalidCurveSeriesError,
    TruncatedCurveError, UnsupportedCurveFormatError,
)
from .parser_limits import MAX_CURVE_BYTES, MAX_CURVE_POINTS, MIN_POINTS, MAX_TEXT_LINE_BYTES, MAX_TEXT_LINES
from .raw_lifecycle import PUBLIC_CODE

RULE = 'raw-recovery-documented-layouts-v1'
MARKER = b'ARGILOTECA_ANON_REC1'
RAW101_FIELDS = [(564,608),(616,656),(660,668),(712,776),(812,824),
                 (888,896),(904,908),(920,928),(936,944),(952,960)]
ANODES = {b'CU',b'CO',b'FE',b'CR',b'MO',b'AG'}

@dataclass
class RecoveredPattern:
    x: list[float]
    intensity: list[float]
    metadata: dict
    uncertainty: list[float] | None = None
    auxiliary: list[float] | None = None

def _bounds(content, offset, size):
    if offset < 0 or size < 0 or offset + size > len(content):
        raise TruncatedCurveError('Declared header/vector exceeds available bytes.')

def _unpack(fmt, content, offset):
    _bounds(content, offset, struct.calcsize('<'+fmt))
    return struct.unpack_from('<'+fmt, content, offset)[0]

def _count(count):
    if count > MAX_CURVE_POINTS: raise CurveLimitExceededError('Too many declared points.')
    if count < MIN_POINTS: raise InvalidCurveSeriesError('Insufficient declared points.')

def _axis(start, step, count, *, allow_zero_scan=False):
    _count(count)
    end = start+(count-1)*step
    lower = -180 if allow_zero_scan else 0
    if not (math.isfinite(start) and math.isfinite(step) and step>0 and lower<=start<end<180):
        raise InvalidCurveHeaderError('Invalid declared angular range.')
    return [start+i*step for i in range(count)]

def _floats(content, offset, count):
    _count(count);_bounds(content,offset,count*4)
    values=[r[0] for r in struct.iter_unpack('<f',memoryview(content)[offset:offset+count*4])]
    if not all(math.isfinite(v) for v in values):raise InvalidCurveSeriesError('Non-finite intensity.')
    return values

def _wave(v):
    return v if math.isfinite(v) and .1<=v<=5 else None

def _base_metadata(content, fmt, *, offset=None, wave=None, axis_kind='two_theta_degrees'):
    return {'recovery_rule':RULE,'detected_format':fmt,'source_sha256':hashlib.sha256(content).hexdigest(),
            'source_size_bytes':len(content),'data_offset':offset,'wavelength_angstrom':_wave(wave) if wave is not None else None,
            'axis_kind':axis_kind,'structural_complete':True,'measurement_complete':False,
            'acquisition_status':'not_verified','requires_curatorial_release':True,
            'warnings':['recovery_does_not_confirm_mineralogy_or_instrument_calibration']}

def _binary(content):
    if content.startswith(b'RAW '):
        _bounds(content,0,156)
        count=_unpack('I',content,4);_count(count)
        if _unpack('I',content,152)!=0:raise UnsupportedCurveFormatError('Multi-range legacy RAW requires separate review.')
        offset=156;start=_unpack('f',content,24);step=_unpack('f',content,12);wave=_unpack('f',content,72)
        fmt='Bruker RAW v1 single-range';m=_base_metadata(content,fmt,offset=offset,wave=wave)
        m.update(axis_provenance='declared_start_float32_at_24',scan_mode=_unpack('I',content,16),
                 time_per_step_seconds=_unpack('f',content,8))
    elif content.startswith(b'RAW2'):
        _bounds(content,0,316)
        if _unpack('H',content,4)!=1:raise UnsupportedCurveFormatError('Multi-range RAW2 requires separate review.')
        header=_unpack('H',content,256)
        if header!=60:raise UnsupportedCurveFormatError('Only the verified 60-byte RAW2 range header is supported.')
        count=_unpack('H',content,258);offset=256+header
        start=_unpack('f',content,272);step=_unpack('f',content,268);wave=_unpack('f',content,190)
        fmt='Bruker RAW2 single-range';m=_base_metadata(content,fmt,offset=offset,wave=wave)
        m.update(axis_provenance='declared_start_float32_at_272',time_per_step_seconds=_unpack('f',content,264))
    elif content.startswith(b'RAW1.01'):
        _bounds(content,0,1016)
        status=_unpack('I',content,8)
        if (status not in {1,3} or _unpack('I',content,12)!=1 or _unpack('I',content,712)!=304
                or _unpack('I',content,968)!=0):raise UnsupportedCurveFormatError('Unverified RAW1.01 range layout.')
        count=_unpack('I',content,716);offset=1016
        start=_unpack('d',content,728);step=_unpack('d',content,888);wave=_unpack('d',content,952)
        fmt='Bruker RAW1.01 single-range';m=_base_metadata(content,fmt,offset=offset,wave=wave)
        m.update(axis_provenance='declared_start_float64_at_728',acquisition_status='completed' if status==1 else 'aborted')
        if start<=0:
            m['warnings'].append('nonpositive_angle_scan_preserved_not_shifted_not_for_mineral_classification')
    elif content.startswith(b'RAW4.00'):
        return _raw4(content)
    else:raise UnsupportedCurveFormatError('No documented binary layout matched.')
    xs=_axis(start,step,count,allow_zero_scan=content.startswith(b'RAW1.01'))
    _bounds(content,offset,count*4)
    if len(content)!=offset+count*4:raise InvalidCurveHeaderError('Unexplained bytes after declared single-range vector.')
    ys=_floats(content,offset,count)
    m.update(points=count,two_theta_start=xs[0],two_theta_end=xs[-1],step=step,
             numerical_payload_sha256=hashlib.sha256(content[offset:]).hexdigest())
    return RecoveredPattern(xs,ys,m)

def _segments(content, start, end=None):
    """Bound segment sizes before advancing; no unbounded sentinel loops."""
    pos=start;items=[]
    for _ in range(10000):
        _bounds(content,pos,8);kind=_unpack('I',content,pos)
        if end is None and kind in {0,160}:return pos,items
        size=_unpack('I',content,pos+4)
        if size<8:raise InvalidCurveHeaderError('Segment does not advance.')
        _bounds(content,pos,size)
        if end is not None and pos+size>end:raise InvalidCurveHeaderError('Segment exceeds declared header region.')
        items.append((pos,kind,size));pos+=size
        if end is not None and pos==end:return pos,items
    raise CurveLimitExceededError('Too many metadata segments.')

def _raw4(content):
    _bounds(content,0,61)
    pos,global_segments=_segments(content,61)
    _bounds(content,pos,160)
    scan=content[pos+32:pos+56].rstrip(b'\0 ')
    if scan not in {b'Locked Coupled',b'Unlocked Coupled'}:
        raise UnsupportedCurveFormatError('Only coupled RAW4 angular scans are verified.')
    count=_unpack('I',content,pos+88);_count(count)
    if _unpack('I',content,pos+136)!=4:raise UnsupportedCurveFormatError('RAW4 datum is not float32.')
    extra=_unpack('I',content,pos+140);offset=pos+160+extra
    _bounds(content,pos+160,extra)
    range_segments=[]
    if extra:_,range_segments=_segments(content,pos+160,offset)
    if len(content)!=offset+count*4:raise InvalidCurveHeaderError('RAW4 vector length or range count requires review.')
    start=_unpack('d',content,pos+72);step=_unpack('d',content,pos+80)
    xs=_axis(start,step,count);ys=_floats(content,offset,count)
    m=_base_metadata(content,'Bruker RAW4 single coupled range',offset=offset,wave=_unpack('d',content,pos+112))
    m.update(points=count,two_theta_start=xs[0],two_theta_end=xs[-1],step=step,
             axis_provenance='declared_primary_range_start_float64',range_offset=pos,
             global_segments=global_segments,range_segments=range_segments,
             numerical_payload_sha256=hashlib.sha256(content[offset:]).hexdigest())
    return RecoveredPattern(xs,ys,m)

def _rigaku_fi(content):
    # Verified Profex loadNew layout only. The old BU-at-22 variant has different
    # offsets and must not silently inherit this adapter.
    _bounds(content,0,3158)
    if content[:4]!=b'FI\0\0' or content[24:26]!=b'BU' or content[22:24]==b'BU':
        raise UnsupportedCurveFormatError('Unverified Rigaku FI variant.')
    count=_unpack('I',content,3154);_count(count)
    if len(content)!=3158+count*4:raise TruncatedCurveError('Rigaku FI count and file length disagree.')
    start=_unpack('f',content,2962);end=_unpack('f',content,2966);step=_unpack('f',content,2970)
    if not (math.isfinite(start) and math.isfinite(end) and math.isfinite(step) and 0<=start<end<180 and step>0):
        raise InvalidCurveHeaderError('Invalid Rigaku FI angular range.')
    if abs(start+(count-1)*step-end)>max(1e-4,abs(end)*1e-6):
        raise InvalidCurveHeaderError('Rigaku FI step and endpoints disagree.')
    # Profex uses the endpoints to avoid accumulating single-precision step
    # rounding. Preserve that declared interpretation; no peak alignment.
    xs=[start+(float(i)/float(count-1))*(end-start) for i in range(count)]
    ys=_floats(content,3158,count)
    m=_base_metadata(content,'Rigaku FI/BU new single-range',offset=3158,wave=_unpack('d',content,1212))
    m.update(points=count,two_theta_start=xs[0],two_theta_end=xs[-1],step=(end-start)/(count-1),
             declared_step=step,axis_provenance='declared_endpoints_linear_interpolation_profex',
             numerical_payload_sha256=hashlib.sha256(content[3158:]).hexdigest())
    return RecoveredPattern(xs,ys,m)

def _lines(content, encoding='ascii'):
    if content.count(b'\n')>MAX_TEXT_LINES:raise CurveLimitExceededError('Too many text lines.')
    try:lines=content.decode(encoding).splitlines()
    except UnicodeDecodeError as exc:raise UnsupportedCurveFormatError('Not a verified ASCII diffraction format.') from exc
    if any(len(l)>MAX_TEXT_LINE_BYTES for l in lines):raise CurveLimitExceededError('Text line too long.')
    return lines

def _ras(content):
    # Non-ASCII operator/site text is discarded; only validated ASCII numeric
    # fields are ever emitted. Do not infer or transcode those free-text values.
    lines=_lines(content,encoding='latin1')
    if not lines or lines[0]!='*RAS_DATA_START' or lines[-1]!='*RAS_DATA_END':raise TruncatedCurveError('RAS outer terminator missing.')
    required=['*RAS_HEADER_START','*RAS_HEADER_END','*RAS_INT_START','*RAS_INT_END']
    if any(lines.count(t)!=1 for t in required):raise UnsupportedCurveFormatError('Only one complete RAS scan is verified.')
    a,b,c,d=[lines.index(t) for t in required]
    if not 0<a<b<c<d<len(lines)-1:raise InvalidCurveHeaderError('RAS marker order invalid.')
    header={}
    for line in lines[a+1:b]:
        match=re.fullmatch(r'\*([A-Z0-9_-]+)\s+"(.*)"',line)
        if not match:raise InvalidCurveHeaderError('Malformed RAS header field.')
        key,value=match.groups()
        if key in header:raise InvalidCurveHeaderError('Duplicate RAS metadata key.')
        header[key]=value
    if header.get('MEAS_SCAN_AXIS_X_INTERNAL') not in {'TwoThetaTheta','TwoTheta'} or header.get('MEAS_SCAN_UNIT_X')!='deg':
        raise UnsupportedCurveFormatError('RAS axis is not explicitly a 2theta scan in degrees.')
    count=float(header.get('MEAS_DATA_COUNT','nan'))
    if not math.isfinite(count) or count!=int(count):raise InvalidCurveHeaderError('Invalid RAS point count.')
    count=int(count);_count(count)
    body=lines[c+1:d]
    if len(body)!=count:raise TruncatedCurveError('RAS declared and actual point counts disagree.')
    values=[]
    for line in body:
        parts=line.split()
        if len(parts)!=3:raise InvalidCurveSeriesError('RAS requires three numerical columns.')
        try:row=tuple(float(v) for v in parts)
        except ValueError as exc:raise InvalidCurveSeriesError('Invalid RAS number.') from exc
        if not all(math.isfinite(v) for v in row) or row[2]<=0:raise InvalidCurveSeriesError('Invalid RAS intensity/attenuator.')
        values.append(row)
    xs,ys,attenuator=map(list,zip(*values))
    expected=_axis(float(header['MEAS_SCAN_START']),float(header['MEAS_SCAN_STEP']),count)
    if any(abs(x-y)>1e-5 for x,y in zip(xs,expected)) or abs(xs[-1]-float(header['MEAS_SCAN_STOP']))>1e-5:
        raise InvalidCurveHeaderError('RAS data and angular header disagree.')
    m=_base_metadata(content,'Rigaku RAS ASCII',wave=float(header.get('HW_XG_WAVE_LENGTH_ALPHA1','nan')))
    m.update(points=count,two_theta_start=xs[0],two_theta_end=xs[-1],step=float(header['MEAS_SCAN_STEP']),
             axis_provenance='explicit_ras_two_theta_degrees',attenuation_handling='third_column_preserved_not_applied',
             axis_internal=header['MEAS_SCAN_AXIS_X_INTERNAL'],
             header_values={k:header[k] for k in ['MEAS_DATA_COUNT','MEAS_SCAN_START','MEAS_SCAN_STOP','MEAS_SCAN_STEP',
                                                'HW_XG_WAVE_LENGTH_ALPHA1','HW_XG_WAVE_LENGTH_ALPHA2','HW_XG_WAVE_LENGTH_BETA'] if k in header},
             body_lines=body)
    return RecoveredPattern(xs,ys,m,auxiliary=attenuator)

def _gsas(content):
    lines=_lines(content)
    if len(lines)<3:raise TruncatedCurveError('Missing GSAS bank.')
    bank=lines[1].split()
    if len(bank)!=10 or bank[0]!='BANK' or bank[4] not in {'CONST','CONS'} or bank[-1]!='ESD':
        raise UnsupportedCurveFormatError('Only one constant-step GSAS ESD bank is verified.')
    count,nrec=int(bank[2]),int(bank[3]);_count(count)
    start,step=float(bank[5]),float(bank[6])
    if not (math.isfinite(start) and math.isfinite(step) and step>0) or any(float(v)!=0 for v in bank[7:9]):
        raise InvalidCurveHeaderError('Unknown GSAS axis coefficients.')
    ys=[];errors=[]
    for index,line in enumerate(lines[2:]):
        if not (len(line)==80 or (index==len(lines)-3 and 16<=len(line)<80 and len(line)%16==0)):
            raise InvalidCurveSeriesError('GSAS ESD requires fixed-width records; only final padding can be completed.')
        line=line.ljust(80)
        blank_seen=False
        for i in range(0,80,16):
            y,e=line[i:i+8],line[i+8:i+16]
            if not y.strip() and not e.strip():blank_seen=True;continue
            if blank_seen:raise InvalidCurveSeriesError('Unexpected GSAS field after padding.')
            if len(ys)>=count:raise InvalidCurveSeriesError('GSAS contains more pairs than declared.')
            try:a,b=float(y),float(e)
            except ValueError as exc:raise InvalidCurveSeriesError('Invalid GSAS fixed-width number.') from exc
            if not math.isfinite(a) or not math.isfinite(b) or b<0:raise InvalidCurveSeriesError('Invalid GSAS intensity/uncertainty.')
            ys.append(a);errors.append(b)
    if len(ys)!=count:raise TruncatedCurveError('GSAS channel count and actual numerical pairs disagree.')
    expected=(count+4)//5
    if len(lines)-2!=expected:raise InvalidCurveHeaderError('GSAS padding/record count invalid.')
    # Header record count can be repaired only because all declared channels
    # and every fixed-width pair have been read. Do not invent a CW/TOF unit.
    if nrec not in {expected,expected-1}:raise InvalidCurveHeaderError('GSAS record count discrepancy requires review.')
    m=_base_metadata(content,'GSAS constant-step ESD',axis_kind='native_gsas_coordinate_unit_unverified')
    m.update(points=count,native_start=start,native_step=step,declared_records=nrec,actual_records=expected,
             bank_tokens=bank,body_lines=[l.ljust(80) for l in lines[2:]],record_count_repaired=nrec!=expected,
             final_record_padding_completed=len(lines[-1])!=80,
             warnings=['cw_or_tof_instrument_metadata_required','no_wavelength_assumed'])
    return RecoveredPattern([start+i*step for i in range(count)],ys,m,uncertainty=errors)

def _read_recoverable_pattern(content):
    if len(content)>MAX_CURVE_BYTES:raise CurveLimitExceededError('File exceeds byte limit.')
    if len(content)<4:raise TruncatedCurveError('Empty or truncated source.')
    if content.startswith((b'RAW ',b'RAW2',b'RAW1.01',b'RAW4.00')):return _binary(content)
    if content.startswith(b'FI\0\0'):return _rigaku_fi(content)
    if content.startswith(b'*RAS_DATA_START'):return _ras(content)
    if len(content.split(b'\n',2))>=2 and content.split(b'\n',2)[1].startswith(b'BANK'):return _gsas(content)
    raise UnsupportedCurveFormatError('No documented recovery layout matched; original retained.')

def read_recoverable_pattern(content):
    try:return _read_recoverable_pattern(content)
    except CurveParseError:raise
    except (ValueError,OverflowError,KeyError) as exc:
        raise InvalidCurveHeaderError('Malformed declared numerical metadata.') from exc

def _copy(out, content, fields):
    for a,b in fields:out[a:b]=content[a:b]

def _anode(out, content, position, size):
    value=content[position:position+size].replace(b'\0',b'').strip().upper()
    if value in ANODES:out[position:position+len(value)]=value

def anonymize_recoverable(content, code, preparation='X'):
    """Return (native derivative bytes, correct extension, verified pattern).

Never invent acquisition status, radiation or positive angles. Every numerical
array, including RAS attenuators and GSAS uncertainties, is re-read and compared.
"""
    if not PUBLIC_CODE.fullmatch(code) or preparation not in {'N','G','C','X'}:raise ValueError('Generated public code and known preparation are required.')
    pattern=read_recoverable_pattern(content);m=pattern.metadata;label=(code+'_'+preparation).encode();extension='.raw'
    if content.startswith(b'FI\0\0'):
        out=bytearray(len(content));_copy(out,content,[(0,16),(24,26),(1212,1236),(2962,2974),(3154,len(content))])
        out[104:104+len(label)]=label;out[204:204+len(MARKER)]=MARKER
    elif content.startswith(b'RAW '):
        out=bytearray(len(content));_copy(out,content,[(0,20),(24,40),(72,80),(152,len(content))])
        out[40:40+len(label)]=label;out[80:80+len(MARKER)]=MARKER
    elif content.startswith(b'RAW2'):
        out=bytearray(len(content));_copy(out,content,[(0,6),(190,202),(210,214),(256,260),(264,276),(302,304),(316,len(content))])
        _anode(out,content,188,2);out[6:6+len(label)]=label;out[80:80+len(MARKER)]=MARKER
    elif content.startswith(b'RAW1.01'):
        out=bytearray(len(content));_copy(out,content,[(0,16),*RAW101_FIELDS,(1016,len(content))])
        _anode(out,content,608,4);out[326:326+len(label)]=label;out[386:386+len(MARKER)]=MARKER
    elif content.startswith(b'RAW4.00'):
        out=bytearray(len(content));out[:8]=content[:8];out[34:34+len(label)]=label
        for i,(p,kind,size) in enumerate(m['global_segments']):
            _copy(out,content,[(p,p+8)])
            if kind==10:
                if size<36:raise InvalidCurveHeaderError('RAW4 VarInfo segment too short.')
                if i==0:out[p+12:p+12+len(MARKER)]=MARKER
            elif kind==30:
                if size<120:raise InvalidCurveHeaderError('RAW4 hardware segment too short.')
                _copy(out,content,[(p+72,p+112)]);_anode(out,content,p+116,4)
        p=m['range_offset'];_copy(out,content,[(p,p+4),(p+72,p+96),(p+100,p+108),(p+112,p+120),(p+136,p+144)])
        scan=content[p+32:p+56].rstrip(b'\0 ');out[p+32:p+32+len(scan)]=scan
        for p,kind,size in m['range_segments']:
            _copy(out,content,[(p,p+8)])
            if kind==50:
                if size<64:raise InvalidCurveHeaderError('RAW4 drive segment too short.')
                name=content[p+12:p+36].rstrip(b'\0 ')
                if name in {b'Theta',b'2Theta',b'Chi',b'Phi',b'BeamTranslation',b'Z-Drive',b'Divergence Slit'}:
                    out[p+12:p+12+len(name)]=name;_copy(out,content,[(p+56,p+64)])
        out[m['data_offset']:]=content[m['data_offset']:]
    elif content.startswith(b'*RAS_DATA_START'):
        extension='.ras'
        lines=['*RAS_DATA_START','*RAS_HEADER_START','*FILE_SAMPLE "'+label.decode()+'"']
        lines += ['*'+k+' "'+v+'"' for k,v in m['header_values'].items()]
        lines += ['*MEAS_SCAN_AXIS_X_INTERNAL "'+m['axis_internal']+'"','*MEAS_SCAN_UNIT_X "deg"',
                  '*RAS_HEADER_END','*RAS_INT_START',*m['body_lines'],'*RAS_INT_END','*RAS_DATA_END']
        out=('\r\n'.join(lines)+'\r\n').encode('ascii')
    else:
        extension='.gsa';bank=m['bank_tokens'].copy();bank[3]=str(m['actual_records'])
        out=(MARKER.decode()+' '+label.decode()+'\n'+' '.join(bank)+'\n'+'\n'.join(m['body_lines'])+'\n').encode('ascii')
    out=bytes(out);check=read_recoverable_pattern(out)
    if (check.x,check.intensity,check.uncertainty,check.auxiliary)!=(pattern.x,pattern.intensity,pattern.uncertainty,pattern.auxiliary):
        raise InvalidCurveSeriesError('Anonymization changed a numerical array.')
    if check.metadata.get('wavelength_angstrom')!=m.get('wavelength_angstrom'):
        raise InvalidCurveHeaderError('Anonymization changed the declared wavelength.')
    return out,extension,pattern
