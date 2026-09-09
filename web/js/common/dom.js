// DOM helpers shared by the pack's frontend scripts. No extension is registered
// here; ComfyUI loads the file like any other, which is harmless.

/** A DOM element with `props` assigned and `children` appended; every element of the pack's dialogs is built here. */
export function el(tag, props = {}, children = []) {
  const element = document.createElement(tag);
  Object.assign(element, props);
  element.append(...children);
  return element;
}
