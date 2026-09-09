// Fake of the browser DOM surface load_image.js touches: `document.createElement`,
// `document.body`, and `Image`. Elements are plain objects with a children list, so
// whatever a script assigns on one (className, textContent, handlers) is what a test
// reads back. `Image` fires `onerror` for a URL containing "broken" and `onload`
// otherwise, on a microtask, the way a real load completes after `src` is set.
export class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parent = null;
    this.open = false;
    // a form control's value is an empty string until something is typed, never undefined
    if (this.tagName === 'INPUT') this.value = '';
  }
  append(...nodes) {
    for (const node of nodes) {
      node.parent = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this);
    this.parent = null;
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
    this.onclose?.();
  }
  focus() {}
}

class FakeImage extends FakeElement {
  constructor() {
    super('img');
  }
  set src(url) {
    this.url = url;
    queueMicrotask(() => (url.includes('broken') ? this.onerror : this.onload)?.());
  }
  get src() {
    return this.url;
  }
}

export const body = new FakeElement('body');
globalThis.document = { body, createElement: (tag) => new FakeElement(tag) };
globalThis.Image = FakeImage;

/** Drop everything the previous test appended to the body. */
export function resetDom() {
  body.children = [];
}

/** Every element under `root`, depth first. */
export function descendants(root) {
  return root.children.flatMap((child) => [child, ...descendants(child)]);
}
