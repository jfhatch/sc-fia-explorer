'use strict';
footer();
loadMeta().then(m => {
  const b = m.build, fv = b.fiadb_version || {};
  $('#asof').textContent = `Data current as of: ${fv.version || '?'} (${fv.descr || ''}, ${(fv.created || '').slice(0, 10)}); latest inventory year ${b.latest_invyr}; `
    + `${(b.locations || 0).toLocaleString()} plot locations and ${(b.visits || 0).toLocaleString()} visits; site built ${(b.built_at || '').slice(0, 10)}.`;
}).catch(() => {});
