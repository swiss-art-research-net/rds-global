const RDS_SEARCH_STATE_PARAM = 'semanticSearch-keyword-search';

if (new URLSearchParams(window.location.search).has(RDS_SEARCH_STATE_PARAM)) {
  document.documentElement.classList.add('rds-search-restoring');

  const clearRestoringState = () => {
    document.documentElement.classList.remove('rds-search-restoring');
    observer.disconnect();
  };

  const observer = new MutationObserver(() => {
    if (document.querySelector('.search-meta')) clearRestoringState();
  });

  const observeSearchResults = () => {
    observer.observe(document.body, { childList: true, subtree: true });
    if (document.querySelector('.search-meta')) clearRestoringState();
  };

  if (document.body) {
    observeSearchResults();
  } else {
    document.addEventListener('DOMContentLoaded', observeSearchResults, { once: true });
  }
}

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
    const searchState = currentParams.get(RDS_SEARCH_STATE_PARAM);
    if (searchState) {
      url.searchParams.set(RDS_SEARCH_STATE_PARAM, searchState);
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
    button.innerHTML = `
      <svg width="10" height="10" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M18.4985 0L10.0005 8.49798L1.50255 0L0 1.50202L8.49851 10L0 18.498L1.50255 20L10.0005 11.502L18.4985 20L20.0011 18.498L11.5025 10L20.0011 1.50202L18.4985 0Z" fill="currentColor"/>
      </svg>`;
    link.appendChild(button);
    badge.appendChild(link);

    return badge;
  }
}

customElements.define('rds-filter-selection', RdsFilterSelection);


function clearSelectedRecord() {
  document.querySelector('.single-row.is-selected')?.classList.remove('is-selected');
}

class RdsRecordSelect extends HTMLElement {
  connectedCallback() {
    if (this._row) return;

    this._row = this.closest('.single-row');
    this.onclick = (e) => {
      const row = this._row;
      if (!row) return;
      if (row.classList.contains('is-selected')) {
        // Re-click on the open record: cancel RS's re-open and close the panel
        // by clicking its close button (which also clears the highlight).
        e.stopPropagation();
        if (row.matches(':hover')) {
          row.classList.add('is-hover-suppressed');
          row.addEventListener(
            'pointerleave',
            () => row.classList.remove('is-hover-suppressed'),
            { once: true }
          );
        }
        document.querySelector('.detail-close')?.click();
        return;
      }
      clearSelectedRecord();
      row.classList.add('is-selected');
    };

    this._handleRowClick = (e) => {
      if (this.contains(e.target)) return;
      if (e.target.closest('a, button, input, select, textarea, rds-copy-popover, rds-copy-value')) return;
      this.click();
    };

    this._row?.addEventListener('click', this._handleRowClick);
  }

  disconnectedCallback() {
    this._row?.removeEventListener('click', this._handleRowClick);
    this._row = null;
  }
}

class RdsRecordDeselect extends HTMLElement {
  connectedCallback() {
    this.onclick = clearSelectedRecord;
  }
}

customElements.define('rds-record-deselect', RdsRecordDeselect);

customElements.define('rds-record-select', RdsRecordSelect);

class RdsItemTruncate extends HTMLElement {
  connectedCallback() {
    if (this._toggleButton) return;

    this._limit = Number.parseInt(this.getAttribute('limit'), 10) || 3;
    this._items = Array.from(this.children);
    this._originalDisplay = new Map(
      this._items.map(item => [
        item,
        {
          value: item.style.getPropertyValue('display'),
          priority: item.style.getPropertyPriority('display')
        }
      ])
    );

    if (this._items.length <= this._limit) return;

    this._expanded = false;
    this._toggleButton = document.createElement('button');
    this._toggleButton.type = 'button';
    this._toggleButton.className = 'rds-item-truncate-toggle';

    this._toggleLabel = document.createElement('span');
    this._toggleButton.append(this._toggleLabel);

    this._toggleButton.addEventListener('click', () => {
      this._expanded = !this._expanded;
      this._render();
    });

    this.appendChild(this._toggleButton);
    this._render();
  }

  _render() {
    this._items.forEach((item, index) => {
      const isHidden = !this._expanded && index >= this._limit;
      item.hidden = isHidden;
      if (isHidden) {
        item.style.display = 'none';
      } else {
        const originalDisplay = this._originalDisplay.get(item);
        if (originalDisplay.value) {
          item.style.setProperty('display', originalDisplay.value, originalDisplay.priority);
        } else {
          item.style.removeProperty('display');
        }
      }
    });

    this._toggleLabel.textContent = this._expanded
      ? 'Show less'
      : `Show all ${this._items.length}`;
    this._toggleButton.classList.toggle('is-expanded', this._expanded);
    this._toggleButton.setAttribute('aria-expanded', String(this._expanded));
  }
}

customElements.define('rds-item-truncate', RdsItemTruncate);

class RdsTextTruncate extends HTMLElement {
  connectedCallback() {
    if (this._initialized) return;
    this._initialized = true;

    const text = this.textContent.trim();
    const lines = Number.parseInt(this.getAttribute('lines'), 10) || 3;
    this._showMoreLabel = this.getAttribute('show-more-label') || 'Show more';
    this._showLessLabel = this.getAttribute('show-less-label') || 'Show less';

    this._text = document.createElement('div');
    this._text.className = 'rds-text-truncate-text';
    this._text.style.setProperty('--rds-text-truncate-lines', String(lines));
    this._text.textContent = text;

    this._toggleButton = document.createElement('button');
    this._toggleButton.type = 'button';
    this._toggleButton.className = 'rds-text-truncate-toggle';
    this._toggleButton.textContent = this._showMoreLabel;
    this._toggleButton.setAttribute('aria-expanded', 'false');
    this._toggleButton.hidden = true;
    this._toggleButton.addEventListener('click', this._handleToggle);

    this.replaceChildren(this._text, this._toggleButton);

    this._resizeObserver = new ResizeObserver(this._measure);
    this._resizeObserver.observe(this._text);
    requestAnimationFrame(this._measure);
  }

  disconnectedCallback() {
    this._resizeObserver?.disconnect();
    this._toggleButton?.removeEventListener('click', this._handleToggle);
  }

  _handleToggle = () => {
    const expanded = !this.classList.contains('is-expanded');
    this.classList.toggle('is-expanded', expanded);
    this._toggleButton.textContent = expanded ? this._showLessLabel : this._showMoreLabel;
    this._toggleButton.setAttribute('aria-expanded', String(expanded));
  };

  _measure = () => {
    if (this.classList.contains('is-expanded')) return;

    this._toggleButton.hidden = this._text.scrollHeight <= this._text.clientHeight + 1;
  };
}

customElements.define('rds-text-truncate', RdsTextTruncate);

async function writeToClipboard(value) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();

    const copied = document.execCommand('copy');
    textarea.remove();
    if (!copied) throw new Error('Clipboard access was denied');
  }
}

class RdsCopyPopover extends HTMLElement {
  static active = null;

  connectedCallback() {
    if (this._initialized) return;
    this._initialized = true;

    const values = {
      URI: this.getAttribute('uri'),
      ID: this.getAttribute('record-id')
    };

    this._trigger = this.querySelector('button');
    if (!this._trigger || !Object.values(values).some(Boolean)) return;

    this._popup = document.createElement('div');
    this._popup.className = 'rds-copy-popover';
    this._popup.hidden = true;
    this._popup.setAttribute('role', 'dialog');
    this._popup.setAttribute('aria-label', 'Copy identifier');

    Object.entries(values).forEach(([label, value]) => {
      if (!value) return;
      this._popup.appendChild(this._createCopyButton(label, value));
    });

    this._status = document.createElement('div');
    this._status.className = 'rds-copy-popover-status';
    this._status.setAttribute('role', 'status');
    this._status.setAttribute('aria-live', 'polite');

    this._popup.appendChild(this._status);
    this._isPortaled = this.getAttribute('placement') === 'left';
    if (this._isPortaled) {
      this._popup.classList.add('rds-copy-popover--left');
      document.body.appendChild(this._popup);
      this._popup.addEventListener('click', event => this._handleClick(event));
    } else {
      this.appendChild(this._popup);
    }

    this._trigger.setAttribute('aria-haspopup', 'dialog');
    this._trigger.setAttribute('aria-expanded', 'false');
    this.addEventListener('click', event => this._handleClick(event));
  }

  disconnectedCallback() {
    clearTimeout(this._closeTimer);
    if (this._isPortaled) this._popup?.remove();
    if (RdsCopyPopover.active === this) RdsCopyPopover.active = null;
  }

  _createCopyButton(label, value) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'rds-copy-popover-action';
    button.dataset.copyValue = value;
    button.dataset.copyLabel = label;

    const icon = document.createElement('img');
    icon.src = '/assets/no-auth/copy-icon.svg';
    icon.alt = '';

    const name = document.createElement('strong');
    name.textContent = label;

    const text = document.createElement('span');
    text.textContent = value;

    button.append(icon, name, text);
    return button;
  }

  _handleClick(event) {
    event.stopPropagation();

    const action = event.target.closest('[data-copy-value]');
    if (action) {
      this._copy(action, action.dataset.copyLabel, action.dataset.copyValue);
    } else if (this._trigger.contains(event.target)) {
      this._popup.hidden ? this.open() : this.close();
    }
  }

  open() {
    RdsCopyPopover.active?.close();
    clearTimeout(this._closeTimer);
    this._status.textContent = '';
    this._popup.style.width = '';
    this._popup.hidden = false;
    this._popup.style.width = `${this._popup.getBoundingClientRect().width}px`;
    if (this._isPortaled) this._positionPortaledPopup();
    this._trigger.setAttribute('aria-expanded', 'true');
    RdsCopyPopover.active = this;
  }

  _positionPortaledPopup() {
    const triggerRect = this._trigger.getBoundingClientRect();
    const popupRect = this._popup.getBoundingClientRect();
    const viewportMargin = 16;

    this._popup.style.left =
      `${Math.max(viewportMargin, triggerRect.left - popupRect.width - 12)}px`;
    this._popup.style.top =
      `${Math.min(
        window.innerHeight - popupRect.height - viewportMargin,
        Math.max(
          viewportMargin,
          triggerRect.top + (triggerRect.height - popupRect.height) / 2
        )
      )}px`;
  }

  close() {
    if (!this._popup) return;
    clearTimeout(this._closeTimer);
    this._status.textContent = '';
    this._resetActions();
    this._popup.hidden = true;
    this._trigger.setAttribute('aria-expanded', 'false');
    if (RdsCopyPopover.active === this) RdsCopyPopover.active = null;
  }

  _resetActions() {
    this._popup.querySelectorAll('[data-copy-value]').forEach(action => {
      action.classList.remove('is-copied');
      action.querySelector('span').textContent = action.dataset.copyValue;
    });
  }

  async _copy(action, label, value) {
    clearTimeout(this._closeTimer);

    try {
      await writeToClipboard(value);
      this._resetActions();
      action.classList.add('is-copied');
      action.querySelector('span').textContent = 'copied';
      this._status.textContent = `${label} copied`;
      this._closeTimer = setTimeout(() => this.close(), 900);
    } catch (error) {
      console.error('Could not copy to clipboard', error);
      this._status.textContent = `Could not copy ${label}`;
    }
  }
}

customElements.define('rds-copy-popover', RdsCopyPopover);

class RdsCopyValue extends HTMLElement {
  connectedCallback() {
    if (this._initialized) return;
    this._initialized = true;

    this._value = this.getAttribute('value');
    if (!this._value) return;
    this._copyLabel = this.getAttribute('copy-label') || 'URI';
    const copyOnly = this.hasAttribute('copy-only');

    const valueText = document.createElement('span');
    valueText.className = 'rds-copy-value-text';
    valueText.textContent = this.textContent.trim() || this._value;

    const copyIcon = document.createElement('img');
    copyIcon.className = 'rds-copy-value-copy-icon';
    copyIcon.src = '/assets/no-auth/copy-icon.svg';
    copyIcon.alt = '';

    this._copyIconButton = document.createElement('button');
    this._copyIconButton.type = 'button';
    this._copyIconButton.className = 'rds-copy-value-copy';
    this._copyIconButton.setAttribute('aria-label', `Copy ${this._copyLabel} ${this._value}`);
    this._copyIconButton.appendChild(copyIcon);

    const actions = document.createElement('span');
    actions.className = 'rds-copy-value-actions';
    if (!copyOnly) {
      const openLink = document.createElement('a');
      openLink.className = 'rds-copy-value-open';
      openLink.href = this._value;
      openLink.target = '_blank';
      openLink.rel = 'noopener noreferrer';
      openLink.setAttribute('aria-label', `Open URI in a new tab: ${this._value}`);

      const openIcon = document.createElement('img');
      openIcon.src = '/assets/no-auth/arrow.svg';
      openIcon.alt = '';
      openLink.appendChild(openIcon);
      openLink.addEventListener('click', event => {
        event.stopPropagation();
        openLink.blur();
      });
      actions.appendChild(openLink);
    }
    actions.appendChild(this._copyIconButton);

    this.replaceChildren(valueText, actions);

    this._copyIconButton.addEventListener('click', event => {
      event.stopPropagation();
      this._copy();
    });

  }

  async _copy() {
    clearTimeout(this._resetTimer);

    try {
      await writeToClipboard(this._value);
      this.classList.add('is-copied');
      this._copyIconButton.blur();
      this._copyIconButton.setAttribute('aria-label', `${this._copyLabel} copied`);
      this._resetTimer = setTimeout(() => {
        this.classList.remove('is-copied');
        this._copyIconButton.setAttribute('aria-label', `Copy ${this._copyLabel} ${this._value}`);
      }, 900);
    } catch (error) {
      console.error(`Could not copy ${this._copyLabel}`, error);
      this._copyIconButton.setAttribute('aria-label', `Could not copy ${this._copyLabel}`);
    }
  }

  disconnectedCallback() {
    clearTimeout(this._resetTimer);
  }
}

customElements.define('rds-copy-value', RdsCopyValue);

document.addEventListener('click', event => {
  const active = RdsCopyPopover.active;
  const clickedInside =
    active?.contains(event.target) || active?._popup?.contains(event.target);
  if (active && !clickedInside) active.close();
}, true);

document.addEventListener('keydown', event => {
  const active = RdsCopyPopover.active;
  if (event.key !== 'Escape' || !active) return;
  active.close();
  active._trigger.focus();
});
