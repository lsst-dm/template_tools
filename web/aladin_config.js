// Aladin Lite backend configuration shared by both dashboards.
//
// Edit ALADIN_SOURCE to pick which host serves the Aladin Lite library and
// the DSS2 color background survey:
//
//   'cds'    - primary: library from aladin.cds.unistra.fr, survey given by
//              its HiPS ID ('P/DSS2/color'), which Aladin resolves through
//              the CDS MocServer.
//   'mirror' - fallback for when the CDS host is unreachable: the npm build
//              of Aladin Lite from jsDelivr (an ES module, pinned version)
//              and the DSS2 color HiPS served directly from ESA's mirror so
//              no CDS lookup is needed.
//
// For a one-off test without editing this file, append ?aladin=cds or
// ?aladin=mirror to the dashboard URL.

const ALADIN_SOURCE = 'mirror';

const ALADIN_SOURCES = {
  cds: {
    script: 'https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js',
    module: false,
    survey: 'P/DSS2/color',
  },
  mirror: {
    script: 'https://cdn.jsdelivr.net/npm/aladin-lite@3.8.2/dist/aladin.js',
    module: true,
    survey: 'https://skies.esac.esa.int/DSSColor',
  },
};

// Resolve the active source, honoring a ?aladin=<name> URL override.
function aladinSource() {
  const override = new URLSearchParams(window.location.search).get('aladin');
  const name = override && override in ALADIN_SOURCES ? override : ALADIN_SOURCE;
  if (override && !(override in ALADIN_SOURCES)) {
    console.warn(`Unknown aladin source '${override}'; using '${ALADIN_SOURCE}'.`);
  }
  return { name, ...ALADIN_SOURCES[name] };
}

// Load Aladin Lite from the active source. Resolves to { A, survey } where
// `A` is the Aladin namespace (already initialized: A.init has resolved) and
// `survey` is the value to pass as the `survey` option to A.aladin().
//
// The CDS build is a classic script that defines a global `A`; the npm build
// is an ES module with `A` as its default export, so the two are loaded
// differently. Call this from a <script type="module"> so you can `await` it.
window.loadAladin = async function loadAladin() {
  const src = aladinSource();
  let A;
  if (src.module) {
    A = (await import(src.script)).default;
  } else {
    await new Promise((resolve, reject) => {
      const el = document.createElement('script');
      el.src = src.script;
      el.charset = 'utf-8';
      el.onload = resolve;
      el.onerror = () => reject(new Error(`Failed to load ${src.script}`));
      document.head.appendChild(el);
    });
    A = window.A;
  }
  await A.init;
  console.info(`Aladin Lite loaded from '${src.name}' source.`);
  return { A, survey: src.survey };
};
