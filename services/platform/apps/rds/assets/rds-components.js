class RdsNavLink extends HTMLElement {
  connectedCallback() {
    this._onClick = this._handleClick.bind(this);
    this.addEventListener('click', this._onClick);
  }

  disconnectedCallback() {
    this.removeEventListener('click', this._onClick);
  }

  _handleClick(e) {
    e.preventDefault();
    const href = this.getAttribute('href');
    if (!href) return;

    const url = new URL(href, window.location.origin);

    const currentParams = new URLSearchParams(window.location.search);
    const searchState = currentParams.get('semanticSearch-keyword-search');
    if (searchState) {
      url.searchParams.set('semanticSearch-keyword-search', searchState);
    }

    window.location.href = url.toString();
  }
}

customElements.define('rds-nav-link', RdsNavLink);

const RDS_DATASET_LABELS = {
  gnd: 'GND',
  ulan: 'ULAN',
  wikidata: 'WD',
  sikart: 'SIKART',
  geonames: 'GeoNames'
};

class RdsDatasetLabel extends HTMLElement {
  connectedCallback() {
    const key = this.getAttribute('key');
    this.textContent = RDS_DATASET_LABELS[key] || key;
  }
}

customElements.define('rds-dataset-label', RdsDatasetLabel);
