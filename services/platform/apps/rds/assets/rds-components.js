class RdsNavLink extends HTMLElement {
  connectedCallback() {
    this._onClick = this._handleClick.bind(this);
    this.addEventListener('click', this._onClick);
    this._syncToggleState();
  }

  disconnectedCallback() {
    this.removeEventListener('click', this._onClick);
  }

  _handleClick(e) {
    e.preventDefault();
    const href = this.getAttribute('href');
    if (!href) return;

    const url = new URL(href, window.location.origin);
    const toggleParam = this.getAttribute('toggle-param');
    if (toggleParam) {
      const toggleValue = this.getAttribute('toggle-value') || '';
      const selectedValues = this._getSelectedValues(toggleParam);

      if (!toggleValue) {
        selectedValues.clear();
      } else if (selectedValues.has(toggleValue)) {
        selectedValues.delete(toggleValue);
      } else {
        selectedValues.add(toggleValue);
      }

      if (selectedValues.size > 0) {
        url.searchParams.set(toggleParam, Array.from(selectedValues).join(','));
      } else {
        url.searchParams.delete(toggleParam);
      }
    }

    const currentParams = new URLSearchParams(window.location.search);
    const searchState = currentParams.get('semanticSearch-keyword-search');
    if (searchState) {
      url.searchParams.set('semanticSearch-keyword-search', searchState);
    }

    Array.from(url.searchParams.entries()).forEach(([key, value]) => {
      if (!value) url.searchParams.delete(key);
    });

    window.location.href = url.toString();
  }

  _getSelectedValues(paramName) {
    const currentParams = new URLSearchParams(window.location.search);
    return new Set(
      (currentParams.get(paramName) || '')
        .split(',')
        .map(value => value.trim())
        .filter(Boolean)
    );
  }

  _syncToggleState() {
    const toggleParam = this.getAttribute('toggle-param');
    if (!toggleParam) return;

    const toggleValue = this.getAttribute('toggle-value') || '';
    const selectedValues = this._getSelectedValues(toggleParam);
    const isActive = toggleValue ? selectedValues.has(toggleValue) : selectedValues.size === 0;
    const button = this.querySelector('.filter-button');

    if (button) {
      button.classList.toggle('active-filter', isActive);
      button.setAttribute('aria-pressed', String(isActive));
    }
  }
}

customElements.define('rds-nav-link', RdsNavLink);

const RDS_CONFIG = fetch('/assets/no_auth/config/datasets.json')
  .then(response => {
    if (!response.ok) {
      throw new Error(`Could not load RDS frontend configuration (${response.status})`);
    }
    return response.json();
  })
  .catch(error => {
    console.error(error);
    return { datasets: {}, types: [] };
  });

function getDatasetLabel(config, key) {
  return config.datasets?.[key]?.name || key;
}

function getTypeLabel(key) {
  return key;
}

class RdsDatasetLabel extends HTMLElement {
  async connectedCallback() {
    const key = this.getAttribute('key');
    this.textContent = key || '';
    const config = await RDS_CONFIG;
    this.textContent = getDatasetLabel(config, key);
  }
}

customElements.define('rds-dataset-label', RdsDatasetLabel);

class RdsFilterSelection extends HTMLElement {
  async connectedCallback() {
    const params = new URLSearchParams(window.location.search);
    const paramName = this.getAttribute('param');
    if (!paramName) return;
    const config = await RDS_CONFIG;

    const values = (params.get(paramName) || '')
      .split(',')
      .map(value => value.trim())
      .filter(Boolean);

    this.replaceChildren(
      ...values.map(value => this._createBadge(value, values, params, paramName, config))
    );
  }

  _createBadge(value, values, params, paramName, config) {
    const badge = document.createElement('span');
    badge.className = 'rds-badge';
    const label = paramName === 'dataset'
      ? getDatasetLabel(config, value)
      : getTypeLabel(value);
    badge.appendChild(document.createTextNode(label));

    const remaining = values.filter(selectedValue => selectedValue !== value);
    const url = new URL('/resource/page:StartDev', window.location.origin);
    const preserveParam = this.getAttribute('preserve-param');
    const preservedValue = preserveParam && params.get(preserveParam);
    if (preservedValue) url.searchParams.set(preserveParam, preservedValue);
    if (remaining.length > 0) url.searchParams.set(paramName, remaining.join(','));

    const link = document.createElement('rds-nav-link');
    link.setAttribute('href', url.pathname + url.search);

    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-label', `Remove ${label}`);
    button.textContent = 'x';
    link.appendChild(button);
    badge.appendChild(link);

    return badge;
  }
}

customElements.define('rds-filter-selection', RdsFilterSelection);
