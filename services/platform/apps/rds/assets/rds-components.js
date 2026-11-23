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
    const checkbox = this.querySelector('input[type="checkbox"]');
    if (checkbox) checkbox.checked = isActive;
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

    const items = document.createElement('rds-item-truncate');
    items.setAttribute('limit', '3');
    if (this.hasAttribute('mobile-limit')) {
      items.setAttribute('mobile-limit', this.getAttribute('mobile-limit'));
    }
    items.append(
      ...values.map(value => this._createBadge(value, values, params, paramName, config))
    );
    this.replaceChildren(items);
  }

  _createBadge(value, values, params, paramName, config) {
    const badge = document.createElement('span');
    badge.className = 'rds-badge';
    const label = paramName === 'dataset'
      ? getDatasetLabel(config, value)
      : getTypeLabel(value);
    badge.appendChild(document.createTextNode(label));

    const remaining = values.filter(selectedValue => selectedValue !== value);
    const url = new URL('/resource/page:Start', window.location.origin);
    const preserveParam = this.getAttribute('preserve-param');
    for (const key of (preserveParam || '').split(',')) {
      const preservedValue = params.get(key);
      if (preservedValue) url.searchParams.set(key, preservedValue);
    }
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
      if (e.target.closest('a, button, input, select, textarea, rds-copy-popover')) return;
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
    this._mobileLimit = Number.parseInt(this.getAttribute('mobile-limit'), 10) || this._limit;
    this._mobileQuery = window.matchMedia('(max-width: 767px)');
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

    if (this._items.length <= Math.min(this._limit, this._mobileLimit)) return;

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
    this._mobileQuery.addEventListener('change', () => this._render());
    this._render();
  }

  _render() {
    const limit = this._mobileQuery.matches ? this._mobileLimit : this._limit;
    this._toggleButton.hidden = this._items.length <= limit;
    this._items.forEach((item, index) => {
      const isHidden = !this._expanded && index >= limit;
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

const RDS_ACTION_ICONS = {
  copy: '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M11 3H3V11H11V3Z" stroke="currentColor" stroke-width="1.5"/><path d="M1 9V1H9" stroke="currentColor" stroke-width="1.5"/></svg>',
  copied: '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M1 0V4H8" transform="translate(2 2.5) rotate(-45 4 2.5)" stroke="currentColor" stroke-width="2"/></svg>',
  source: '<svg width="11" height="12" viewBox="0 0 11 12" aria-hidden="true"><path d="M1.1201 11.0144L0 9.89426L8.32898 1.55091H1.89556L1.90992 0H11V9.10444H9.43473L9.44909 2.67102L1.1201 11.0144Z" fill="currentColor"/></svg>',
  rds: '<svg width="16" height="10" viewBox="0 0 18 12" fill="none" aria-hidden="true"><path d="M1 6H16M11 1L16 6L11 11" stroke="currentColor" stroke-width="1.5"/></svg>',
  close: '<svg width="10" height="10" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M18.4985 0L10.0005 8.49798L1.50255 0L0 1.50202L8.49851 10L0 18.498L1.50255 20L10.0005 11.502L18.4985 20L20.0011 18.498L11.5025 10L20.0011 1.50202L18.4985 0Z" fill="currentColor"/></svg>'
};

const RDS_POPOVER_LEAVE_DELAY = 400;

class RdsCopyPopover extends HTMLElement {
  static active = null;

  connectedCallback() {
    if (this._initialized) return;
    this._initialized = true;

    this._uri = this.getAttribute('uri');
    if (!this._uri) return;

    this._isRdsRecord = Boolean(this.getAttribute('rds-record'));
    this._recordId = this.getAttribute('record-id');
    if (this._recordId === null && (this._isRdsRecord || this.getAttribute('copy-id'))) {
      this._recordId = this._uri.replace(/^.*[/#]/, '');
    }

    this._trigger = this.querySelector('button') || this._createTextTrigger();
    if (!this._trigger) return;

    this._trigger.setAttribute('aria-haspopup', 'dialog');
    this._trigger.setAttribute('aria-expanded', 'false');
    this._trigger.addEventListener('click', event => {
      event.stopPropagation();
      this._toggle(event.detail === 0);
    });
    this._trigger.addEventListener('keydown', event => this._handleTriggerKeydown(event));
    this._trigger.addEventListener('pointerenter', () => this._cancelLeaveClose());
    this._trigger.addEventListener('pointerleave', event => this._scheduleLeaveClose(event));
  }

  disconnectedCallback() {
    this.close();
  }

  _createTextTrigger() {
    const text = this.textContent.trim();
    if (!text) return null;

    const trigger = document.createElement('span');
    trigger.className = 'rds-copy-trigger';
    trigger.setAttribute('role', 'button');
    trigger.tabIndex = 0;
    trigger.textContent = text;
    this.replaceChildren(trigger);
    return trigger;
  }

  _createPopup() {
    const popup = document.createElement('div');
    popup.className = 'rds-copy-popover';
    popup.hidden = true;
    popup.setAttribute('role', 'dialog');
    popup.setAttribute('aria-label', `Actions for ${this._uri}`);

    this._preview = document.createElement('div');
    this._preview.className = 'rds-copy-popover-preview';
    this._preview.setAttribute('aria-hidden', 'true');

    this._previewIcon = document.createElement('span');
    this._previewIcon.className = 'rds-copy-popover-preview-icon';
    this._previewIcon.innerHTML = RDS_ACTION_ICONS.copied;
    this._previewIcon.hidden = true;

    this._previewVerb = document.createElement('span');
    this._previewVerb.className = 'rds-copy-popover-preview-verb';

    this._previewStart = document.createElement('span');
    this._previewStart.className = 'rds-copy-popover-preview-start';

    this._previewEnd = document.createElement('span');
    this._previewEnd.className = 'rds-copy-popover-preview-end';

    const previewValue = document.createElement('span');
    previewValue.className = 'rds-copy-popover-preview-value';
    previewValue.append(this._previewStart, this._previewEnd);

    this._preview.append(this._previewIcon, this._previewVerb, previewValue);
    this._preview.addEventListener('mousedown', event => event.preventDefault());
    popup.appendChild(this._preview);

    const controls = document.createElement('div');
    controls.className = 'rds-copy-popover-controls';
    popup.appendChild(controls);

    const previewTarget = event => event.target.closest('.rds-copy-popover-action');
    popup.addEventListener('pointerover', event => {
      const action = previewTarget(event);
      if (action) {
        this._showPreview(action);
      } else if (event.target.closest('.rds-copy-popover-close')) {
        this._showPreview(null);
      }
    });
    popup.addEventListener('pointerleave', () => this._showPreview(null));
    controls.addEventListener('focusin', event => this._showPreview(previewTarget(event)));
    controls.addEventListener('focusout', () => this._showPreview(null));

    controls.appendChild(this._createCopyAction('URI', this._uri));
    if (this._recordId) {
      controls.appendChild(this._createCopyAction('ID', this._recordId));
    }
    controls.appendChild(
      this._createLinkAction(
        'Source',
        this._uri,
        RDS_ACTION_ICONS.source,
        `Open at source in a new tab: ${this._uri}`,
        this._uri.replace(/^https?:\/\//, '').split('/')[0]
      )
    );
    if (this._isRdsRecord) {
      controls.appendChild(
        this._createLinkAction(
          'Open in RDS',
          `/resource/?uri=${encodeURIComponent(this._uri)}`,
          RDS_ACTION_ICONS.rds,
          `Open the RDS record in a new tab: ${this._uri}`,
          'RDS record'
        )
      );
    }

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'rds-copy-popover-close';
    closeButton.setAttribute('aria-label', 'Close');
    closeButton.innerHTML = RDS_ACTION_ICONS.close;
    controls.appendChild(closeButton);

    this._status = document.createElement('div');
    this._status.className = 'rds-copy-popover-status';
    this._status.setAttribute('role', 'status');
    this._status.setAttribute('aria-live', 'polite');
    popup.appendChild(this._status);

    popup.addEventListener('click', event => this._handlePopupClick(event));
    popup.addEventListener('keydown', event => this._handlePopupKeydown(event));
    popup.addEventListener('pointerenter', () => this._cancelLeaveClose());
    popup.addEventListener('pointerleave', event => this._scheduleLeaveClose(event));
    return popup;
  }

  _scheduleLeaveClose(event) {
    if (event.pointerType !== 'mouse' || !this._isOpen()) return;
    this._cancelLeaveClose();
    this._leaveTimer = setTimeout(() => this.close(), RDS_POPOVER_LEAVE_DELAY);
  }

  _cancelLeaveClose() {
    clearTimeout(this._leaveTimer);
  }

  _showPreview(action, verb) {
    if (this._previewLocked && !verb) return;

    this._previewAction?.classList.remove('is-previewed');
    this._previewAction = action || null;

    if (!action) {
      this._preview.classList.remove('is-visible');
      return;
    }

    action.classList.add('is-previewed');

    const value = action.dataset.previewValue;
    const tailLength = 6;
    const isLong = value.length > tailLength + 6;
    this._previewIcon.hidden = !verb;
    this._previewVerb.textContent = verb || action.dataset.previewVerb;
    this._previewStart.textContent = isLong ? value.slice(0, -tailLength) : '';
    this._previewEnd.textContent = isLong ? value.slice(-tailLength) : value;
    this._preview.classList.add('is-visible');
  }

  _createCopyAction(label, value) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'rds-copy-popover-action';
    button.dataset.copyValue = value;
    button.dataset.copyLabel = label;
    button.dataset.previewVerb = 'Copy';
    button.dataset.previewValue = value;
    button.setAttribute('aria-label', `Copy ${label} ${value}`);

    const icon = document.createElement('span');
    icon.className = 'rds-copy-popover-icon';
    icon.innerHTML = RDS_ACTION_ICONS.copy;

    const text = document.createElement('span');
    text.className = 'rds-copy-popover-text';
    text.textContent = `Copy ${label}`;

    button.append(icon, text);
    return button;
  }

  _createLinkAction(label, href, iconMarkup, ariaLabel, previewValue) {
    const link = document.createElement('a');
    link.className = 'rds-copy-popover-action';
    link.dataset.previewVerb = 'Open';
    link.dataset.previewValue = previewValue;
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', ariaLabel);

    const text = document.createElement('span');
    text.className = 'rds-copy-popover-text';
    text.textContent = label;

    const icon = document.createElement('span');
    icon.className = 'rds-copy-popover-icon';
    icon.innerHTML = iconMarkup;

    link.append(text, icon);
    return link;
  }

  _getActions() {
    return Array.from(this._popup.querySelectorAll('.rds-copy-popover-action'));
  }

  _isOpen() {
    return Boolean(this._popup) && !this._popup.hidden;
  }

  _toggle(focusFirstAction) {
    if (this._isOpen()) {
      this.close();
    } else {
      this.open(focusFirstAction);
    }
  }

  _handleTriggerKeydown(event) {
    const isButton = this._trigger.tagName === 'BUTTON';
    if (!isButton && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      event.stopPropagation();
      this._toggle(true);
    } else if (event.key === 'Tab' && !event.shiftKey && this._isOpen()) {
      event.preventDefault();
      this._getActions()[0]?.focus();
    }
  }

  _handlePopupClick(event) {
    event.stopPropagation();

    if (this._preview.contains(event.target)) {
      const action = this._previewAction;
      if (!action) return;
      if (action.dataset.copyValue !== undefined) {
        this._copy(action);
      } else {
        action.click();
      }
      return;
    }

    const copyAction = event.target.closest('[data-copy-value]');
    if (copyAction) {
      this._copy(copyAction);
    } else if (event.target.closest('.rds-copy-popover-close')) {
      this.close();
    } else if (event.target.closest('a')) {
      setTimeout(() => this.close(), 0);
    }
  }

  _handlePopupKeydown(event) {
    if (event.key !== 'Tab') return;

    const controls = Array.from(this._popup.querySelectorAll('a, button'));
    const edge = event.shiftKey ? controls[0] : controls[controls.length - 1];
    if (document.activeElement !== edge) return;

    event.preventDefault();
    this.close();
    this._trigger.focus();
  }

  open(focusFirstAction = false) {
    RdsCopyPopover.active?.close();
    clearTimeout(this._closeTimer);
    clearTimeout(this._leaveTimer);

    if (!this._popup) this._popup = this._createPopup();
    if (!this._popup.isConnected) document.body.appendChild(this._popup);

    this._popup.hidden = false;
    const actions = this._getActions();
    actions.forEach(action => {
      action.style.minWidth = '';
    });
    actions
      .map(action => action.getBoundingClientRect().width)
      .forEach((width, index) => {
        actions[index].style.minWidth = `${width}px`;
      });
    this._position();
    this._trigger.setAttribute('aria-expanded', 'true');
    RdsCopyPopover.active = this;

    if (focusFirstAction) this._getActions()[0]?.focus();
  }

  _position() {
    const viewportMargin = 16;
    const gap = 12;
    const arrowInset = 14;
    const triggerBox = this._trigger.getBoundingClientRect();
    const firstLine = this._trigger.getClientRects()[0] || triggerBox;
    const popupBox = this._popup.getBoundingClientRect();
    const previewHeight = this._preview.offsetHeight;
    const fitsAbove = firstLine.top - popupBox.height - previewHeight - gap >= 0;
    const top = fitsAbove
      ? firstLine.top - popupBox.height - gap
      : triggerBox.bottom + gap;
    const anchorLeft = fitsAbove ? firstLine.left : triggerBox.left;
    const left = Math.max(
      viewportMargin,
      Math.min(anchorLeft, window.innerWidth - popupBox.width - viewportMargin)
    );
    const arrowLeft = Math.max(
      arrowInset,
      Math.min(anchorLeft - left + arrowInset, popupBox.width - arrowInset * 2)
    );

    this._popup.classList.toggle('is-below', !fitsAbove);
    this._popup.style.left = `${left}px`;
    this._popup.style.top = `${top}px`;
    this._popup.style.setProperty('--rds-copy-popover-arrow-left', `${arrowLeft}px`);
  }

  close() {
    clearTimeout(this._closeTimer);
    clearTimeout(this._leaveTimer);
    if (RdsCopyPopover.active === this) RdsCopyPopover.active = null;
    if (!this._popup) return;

    const hadFocus = this._popup.contains(document.activeElement);
    this._previewLocked = false;
    this._showPreview(null);
    this._resetActions();
    this._status.textContent = '';
    this._popup.hidden = true;
    this._popup.remove();
    this._trigger.setAttribute('aria-expanded', 'false');
    if (hadFocus && this.isConnected) this._trigger.focus();
  }

  _resetActions() {
    this._popup.querySelectorAll('[data-copy-value]').forEach(action => {
      action.classList.remove('is-copied');
      action.querySelector('.rds-copy-popover-icon').innerHTML = RDS_ACTION_ICONS.copy;
      action.querySelector('.rds-copy-popover-text').textContent =
        `Copy ${action.dataset.copyLabel}`;
    });
  }

  async _copy(action) {
    clearTimeout(this._closeTimer);
    const label = action.dataset.copyLabel;

    try {
      await writeToClipboard(action.dataset.copyValue);
      this._resetActions();
      action.classList.add('is-copied');
      action.querySelector('.rds-copy-popover-icon').innerHTML = RDS_ACTION_ICONS.copied;
      action.querySelector('.rds-copy-popover-text').textContent = 'Copied';
      this._showPreview(action, 'Copied');
      this._previewLocked = true;
      this._status.textContent = `${label} copied`;
      this._closeTimer = setTimeout(() => this.close(), 900);
    } catch (error) {
      console.error('Could not copy to clipboard', error);
      this._status.textContent = `Could not copy ${label}`;
    }
  }
}

customElements.define('rds-copy-popover', RdsCopyPopover);

let rdsLastPointerType = 'mouse';

document.addEventListener('pointerdown', event => {
  rdsLastPointerType = event.pointerType;
}, true);

document.addEventListener('click', event => {
  const active = RdsCopyPopover.active;
  const clickedInside =
    active?.contains(event.target) || active?._popup?.contains(event.target);
  if (!active || clickedInside) return;

  active.close();

  const isTouch = (event.pointerType || rdsLastPointerType) === 'touch';
  const opensRecord =
    event.target.closest('.single-row') &&
    !event.target.closest(
      'a, button, input, select, textarea, rds-copy-popover, rds-record-select'
    );
  if (isTouch && opensRecord) {
    event.preventDefault();
    event.stopPropagation();
  }
}, true);

document.addEventListener('keydown', event => {
  const active = RdsCopyPopover.active;
  if (event.key !== 'Escape' || !active) return;
  active.close();
  active._trigger.focus();
});

function selectedGroupRows() {
  const group = document.querySelector('.single-row.is-selected')?.closest('.group-members');
  return Array.from(group?.querySelectorAll('rds-graph-hover') || []);
}

function findGroupRow(uri) {
  return selectedGroupRows().find(marker => marker.getAttribute('uri') === uri)?.closest('.single-row') || null;
}

function selectGroupRecord(uri) {
  findGroupRow(uri)?.querySelector('rds-record-select')?.click();
}

class RdsGraphHover extends HTMLElement {
  connectedCallback() {
    this._row = this.closest('.single-row');
    this._enter = () => this._focus(this.getAttribute('uri'));
    this._leave = () => this._focus(null);
    this._focusOut = event => {
      if (!this._row.contains(event.relatedTarget)) this._focus(null);
    };
    this._row?.addEventListener('mouseenter', this._enter);
    this._row?.addEventListener('mouseleave', this._leave);
    this._row?.addEventListener('focusin', this._enter);
    this._row?.addEventListener('focusout', this._focusOut);
  }

  _focus(uri) {
    document.dispatchEvent(new CustomEvent('rds-graph-focus', { detail: { uri } }));
  }

  disconnectedCallback() {
    this._row?.removeEventListener('mouseenter', this._enter);
    this._row?.removeEventListener('mouseleave', this._leave);
    this._row?.removeEventListener('focusin', this._enter);
    this._row?.removeEventListener('focusout', this._focusOut);
  }
}

customElements.define('rds-graph-hover', RdsGraphHover);

function selectLinkMapRecords(records) {
  const neighbors = new Map(records.map(record => [record.subject.value, new Set()]));
  const displayed = records.filter(record => record.displayIndex).map(record => record.subject.value).sort();

  for (const record of records) {
    const source = record.subject.value;
    for (const target of JSON.parse(record.localMatches?.value || '[]')) {
      if (target === source || !neighbors.has(target)) continue;
      neighbors.get(source).add(target);
      neighbors.get(target).add(source);
    }
  }
  const adjacency = new Map(Array.from(neighbors, ([uri, links]) => [uri, Array.from(links).sort()]));
  const kept = new Set(displayed);

  while (true) {
    const visited = new Set();
    let shortest = null;
    for (const source of displayed) {
      if (visited.has(source)) continue;
      const component = [source];
      visited.add(source);
      for (let index = 0; index < component.length; index++) {
        for (const next of adjacency.get(component[index])) {
          if (!kept.has(next) || visited.has(next)) continue;
          component.push(next);
          visited.add(next);
        }
      }
      const members = new Set(component);
      const queue = component.slice();
      const previous = new Map(component.map(uri => [uri, null]));
      for (let index = 0; index < queue.length; index++) {
        const uri = queue[index];
        if (kept.has(uri) && !members.has(uri)) {
          const path = [];
          for (let node = uri; node !== null; node = previous.get(node)) path.push(node);
          if (!shortest || path.length < shortest.length) shortest = path;
          break;
        }
        for (const next of adjacency.get(uri)) {
          if (previous.has(next)) continue;
          previous.set(next, uri);
          queue.push(next);
        }
      }
    }
    if (!shortest) return records.filter(record => kept.has(record.subject.value));
    shortest.forEach(uri => kept.add(uri));
  }
}

const rdsLinkMapRecords = new Map();
let rdsLinkMapRequestId = 0;

function renderLinkMapEvent(host, target, data) {
  const trigger = document.createElement('mp-event-trigger');
  trigger.id = `${target}-ready`;
  trigger.setAttribute('type', 'Component.TemplateUpdate');
  trigger.setAttribute('targets', JSON.stringify([target]));
  trigger.setAttribute('on', '["mounted"]');
  trigger.setAttribute('data', JSON.stringify(data));
  const template = document.createElement('mp-template-item');
  template.append(trigger);
  host.append(template);
}

class RdsLinkMapLoader extends HTMLElement {
  load() {
    if (this._loaded) return;
    const rows = JSON.parse(this.getAttribute('rows') || '[]');
    const groupKey = JSON.stringify(rows.slice().sort((a, b) => a.subject.value.localeCompare(b.subject.value)));
    const host = document.getElementById('rds-link-map-host');
    if (host?.dataset.groupKey === groupKey && host.dataset.recordsReady === 'true') {
      this._loaded = true;
      return;
    }
    const requestId = ++rdsLinkMapRequestId;
    if (host) {
      host.dataset.groupKey = groupKey;
      host.dataset.requestId = String(requestId);
      delete host.dataset.recordsReady;
      delete host.dataset.error;
    }
    const current = this.getAttribute('current');
    const cached = rdsLinkMapRecords.get(groupKey);
    this._loaded = true;
    if (cached) {
      if (host) host.dataset.recordsReady = 'true';
      const bindings = cached.map(record => ({ ...record, current: { value: current }, requestId: { value: String(requestId) } }));
      renderLinkMapEvent(this, 'rds-link-map-paths', { bindings });
      return;
    }
    renderLinkMapEvent(this, 'rds-link-map-paths', { bindings: [] });
    renderLinkMapEvent(this, 'rds-link-map-load', {
      rows, requestId, subjectUri: current, memberCount: Number(this.getAttribute('member-count'))
    });
  }
}

customElements.define('rds-link-map-loader', RdsLinkMapLoader);

class RdsLinkMapPaths extends HTMLElement {
  connectedCallback() {
    if (this.firstElementChild) return;
    const records = JSON.parse(this.getAttribute('records') || '[]');
    if (!records.length) return;
    const bindings = selectLinkMapRecords(records);
    const host = document.getElementById('rds-link-map-host');
    if (host?.dataset.requestId !== this.getAttribute('request-id')) return;
    const key = host.dataset.groupKey;
    host.dataset.recordsReady = 'true';
    rdsLinkMapRecords.delete(key);
    rdsLinkMapRecords.set(key, bindings);
    if (rdsLinkMapRecords.size > 20) rdsLinkMapRecords.delete(rdsLinkMapRecords.keys().next().value);
    renderLinkMapEvent(this, 'rds-link-map-paths', { bindings });
  }
}

customElements.define('rds-link-map-paths', RdsLinkMapPaths);

let rdsPanelGraphOpen = false;
let rdsActivePanelGraph = null;

class RdsPanelGraph extends HTMLElement {
  connectedCallback() {
    if (this._initialized) return;
    this._initialized = true;
    this._current = this.getAttribute('current');
    this._root = this.closest('.detail-panel-graph');
    this._panel = this.closest('.detail-panel');
    this._host = document.getElementById('rds-link-map-host');
    this._slot = this._root.querySelector('.detail-panel-graph-map');
    rdsActivePanelGraph = this;
    this._syncHost = () => {
      if (!this.isConnected || !this._host || !this._slot) return;
      const box = this._slot.getBoundingClientRect();
      const ready = this._host.dataset.renderedRequest === this._host.dataset.requestId && Boolean(this._host.dataset.renderedRequest);
      const failed = this._host.dataset.error;
      const error = this._slot.querySelector('.rds-link-map-error');
      if (error) {
        error.hidden = !rdsPanelGraphOpen || !failed;
        const message = error.querySelector('span');
        if (message && message.textContent !== (failed || '')) message.textContent = failed || '';
      }
      this._host.hidden = !rdsPanelGraphOpen;
      this._host.style.visibility = ready && !failed ? 'visible' : 'hidden';
      const loading = this._slot.querySelector('.rds-link-map-loading');
      if (loading) loading.hidden = !rdsPanelGraphOpen || ready || Boolean(failed);
      Object.assign(this._host.style, {
        position: 'fixed', top: `${box.top}px`, left: `${box.left}px`, width: `${Math.max(0, box.width - 32)}px`,
        zIndex: String((Number(getComputedStyle(this._panel).zIndex) || 4) + 1),
        background: getComputedStyle(this._panel).backgroundColor
      });
      const height = rdsPanelGraphOpen ? (ready && !failed ? `${this._host.getBoundingClientRect().height}px` : '40px') : '0px';
      if (this._slot.style.height !== height) this._slot.style.height = height;
      if (rdsPanelGraphOpen && box.width > 0 && this._graphWidth !== box.width) {
        this._graphWidth = box.width;
        this._cy?.resize();
        this._place();
      }
    };
    this._hostObserver = new ResizeObserver(this._syncHost);
    this._hostObserver.observe(this._panel);
    if (this._host) this._hostObserver.observe(this._host);
    window.addEventListener('scroll', this._syncHost, true);
    window.addEventListener('resize', this._syncHost);

    this._errorObserver = new MutationObserver(() => {
      const requestId = this._host?.dataset.requestId;
      if (!requestId || !this.isConnected) return;
      const selector = `[data-rds-request="${requestId}"] .error-notification, [data-rds-graph-request="${requestId}"] .error-notification`;
      const failure = this._root.querySelector(selector) || this._host.querySelector(selector);
      if (failure) {
        this._host.dataset.error = failure.textContent.trim() || 'Could not load connections.';
        const loader = this._root.querySelector('rds-link-map-loader');
        if (loader) loader._loaded = false;
        this._syncHost();
      }
    });
    this._errorObserver.observe(this._root, { childList: true, subtree: true });
    if (this._host) this._errorObserver.observe(this._host, { childList: true, subtree: true });

    this._onRootClick = event => {
      if (event.target.closest('.rds-link-map-retry')) {
        delete this._host.dataset.recordsReady;
        rdsLinkMapRecords.delete(this._host.dataset.groupKey);
        this._root.querySelector('rds-link-map-loader')?.load();
        this._syncHost();
        return;
      }
      if (event.target.closest('.detail-panel-graph-toggle')) {
        rdsPanelGraphOpen = !rdsPanelGraphOpen;
        this._render();
        if (rdsPanelGraphOpen) requestAnimationFrame(() => {
          this._cy?.resize();
          this._place();
        });
        return;
      }
      const badge = event.target.closest('.detail-panel-graph-badges [data-uri]');
      if (badge && badge.dataset.uri !== this._current) selectGroupRecord(badge.dataset.uri);
    };
    this._onExternalFocus = event => this._mark(event.detail.uri);
    this._onPanelOver = event => {
      const badge = event.target.closest('.detail-panel-graph-badges [data-uri]');
      const item = event.target.closest('.detail-related-record[data-node]');
      if (badge) this._mark(badge.dataset.uri);
      else if (item) this._mark(this._itemNode(item), true);
      else if (!event.target.closest('.detail-panel-graph-map')) this._mark(null);
    };
    this._onPanelLeave = () => this._mark(null);

    this._root?.addEventListener('click', this._onRootClick);
    this._panel?.addEventListener('mouseover', this._onPanelOver);
    this._panel?.addEventListener('mouseleave', this._onPanelLeave);
    document.addEventListener('rds-graph-focus', this._onExternalFocus);

    this._render();
    this._bindGraph();
    this._bindTimer = setInterval(() => this._bindGraph(), 300);
  }

  _render() {
    if (!this._root) return;
    const toggle = this._root.querySelector('.detail-panel-graph-toggle');
    const badges = this._root.querySelector('.detail-panel-graph-badges');
    this._root.classList.toggle('is-closed', !rdsPanelGraphOpen);
    toggle?.setAttribute('aria-expanded', String(rdsPanelGraphOpen));
    if (badges) badges.hidden = rdsPanelGraphOpen;
    this._syncHost();
    if (rdsPanelGraphOpen) requestAnimationFrame(() => {
      if (this.isConnected) this._root.querySelector('rds-link-map-loader')?.load();
    });
    badges?.querySelectorAll('[data-uri]').forEach(badge => {
      const isCurrent = badge.dataset.uri === this._current;
      badge.classList.toggle('is-current', isCurrent);
      badge.setAttribute('aria-pressed', String(isCurrent));
    });
  }

  _bindGraph() {
    const container = Array.from(this._host?.querySelectorAll('div') || [])
      .find(element => element._cyreg?.cy);
    const cy = container?._cyreg?.cy;
    if (!cy || cy.destroyed?.()) return;
    if (cy === this._cy) {
      this._finishGraph();
      return;
    }
    this._cy = cy;
    this._container = container;

    cy.off('tap', 'node');
    cy.off('tap', 'edge');
    this._graphTap = event => {
      const uri = this._nodeId(event.cyTarget || event.target);
      if (uri !== this._current && findGroupRow(uri)) selectGroupRecord(uri);
    };
    this._graphOver = event => {
      const uri = this._nodeId(event.cyTarget || event.target);
      container.style.cursor = uri !== this._current && findGroupRow(uri) ? 'pointer' : '';
      this._mark(uri);
    };
    this._graphOut = () => {
      container.style.cursor = '';
      this._mark(null);
    };
    this._graphLayout = () => {
      this._place();
      this._finishGraph();
    };
    this._graphViewport = () => {
      if (!this._placing && Math.abs(cy.zoom() - (this._zoom || 1)) > 0.001) this._place();
    };
    cy.on('tap', 'node', this._graphTap);
    cy.on('mouseover', 'node', this._graphOver);
    cy.on('mouseout', 'node', this._graphOut);
    cy.on('layoutstop', this._graphLayout);
    cy.on('viewport', this._graphViewport);
    this._finishGraph();
  }

  _finishGraph() {
    const cy = this._cy;
    if (!cy || cy.destroyed?.() || !cy.nodes().length || cy.width() <= 0) return;
    const requestId = this._container.closest('[data-rds-graph-request]')?.dataset.rdsGraphRequest;
    if (requestId !== this._host.dataset.requestId) return;
    if (!this._container.dataset.rdsPositioned) {
      this._place();
      this._container.dataset.rdsPositioned = 'true';
    }
    const current = this._node(this._current);
    if (current && !current.hasClass('rds-map-current')) {
      cy.nodes().removeClass('rds-map-current');
      current.addClass('rds-map-current');
      this._mark(null);
    }
    this._host.dataset.renderedRequest = requestId;
    this._syncHost();
  }

  _nodeId(node) {
    return node?.data('node')?.value || null;
  }

  _node(uri) {
    if (!this._cy || !uri) return null;
    const node = this._cy.nodes().filter((index, element) => this._nodeId(element) === uri);
    return node.length ? node : null;
  }

  _itemNode(item) {
    return this._node(item.dataset.node) ? item.dataset.node : item.dataset.groupNode;
  }

  _place() {
    const cy = this._cy;
    if (!cy || cy.destroyed?.() || !cy.nodes().length) return;
    const box = cy.elements().boundingBox();
    const width = cy.width();
    const zoom = box.w > width - 8 ? (width - 8) / box.w : 1;
    this._placing = true;
    this._zoom = zoom;
    cy.zoom(zoom);
    cy.pan({ x: (width - box.w * zoom) / 2 - box.x1 * zoom, y: 10 - box.y1 * zoom });
    this._placing = false;
    this._mark(null);
  }

  _mark(uri, pair) {
    const cy = this._cy;
    if (cy && !cy.destroyed?.()) {
      const current = this._node(this._current);
      const target = this._node(uri);
      cy.batch(() => {
        cy.elements().removeClass('rds-map-muted');
        if (pair && current && target) {
          const keep = current.union(target).union(current.edgesWith(target));
          cy.elements().difference(keep).addClass('rds-map-muted');
        } else {
          const focus = target || current;
          if (focus) cy.elements().difference(focus.closedNeighborhood()).addClass('rds-map-muted');
        }
      });
    }

    this._panel?.querySelectorAll('.detail-related-record[data-node]').forEach(item => {
      item.classList.toggle('is-graph-highlighted', uri !== null && this._itemNode(item) === uri);
    });
    selectedGroupRows().forEach(marker => {
      marker.closest('.single-row')?.classList.toggle(
        'is-graph-highlighted',
        uri !== null && marker.getAttribute('uri') === uri
      );
    });
  }

  disconnectedCallback() {
    this._hostObserver?.disconnect();
    this._errorObserver?.disconnect();
    window.removeEventListener('scroll', this._syncHost, true);
    window.removeEventListener('resize', this._syncHost);
    requestAnimationFrame(() => {
      if (rdsActivePanelGraph === this) {
        if (this._host) this._host.hidden = true;
        rdsActivePanelGraph = null;
      }
    });
    clearInterval(this._bindTimer);
    const cy = this._cy;
    if (cy && !cy.destroyed?.()) {
      cy.off('tap', 'node', this._graphTap);
      cy.off('mouseover', 'node', this._graphOver);
      cy.off('mouseout', 'node', this._graphOut);
      cy.off('layoutstop', this._graphLayout);
      cy.off('viewport', this._graphViewport);
    }
    this._root?.removeEventListener('click', this._onRootClick);
    this._panel?.removeEventListener('mouseover', this._onPanelOver);
    this._panel?.removeEventListener('mouseleave', this._onPanelLeave);
    document.removeEventListener('rds-graph-focus', this._onExternalFocus);
    document.querySelectorAll('.single-row.is-graph-highlighted')
      .forEach(row => row.classList.remove('is-graph-highlighted'));
    this._initialized = false;
    this._cy = null;
  }
}

customElements.define('rds-panel-graph', RdsPanelGraph);

window.addEventListener('scroll', event => {
  const active = RdsCopyPopover.active;
  if (active && !active._popup?.contains(event.target)) active.close();
}, true);

window.addEventListener('resize', () => {
  RdsCopyPopover.active?.close();
});
