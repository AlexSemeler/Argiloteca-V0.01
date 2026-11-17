/*
 * SPDX-FileCopyrightText: 2023 CERN.
 * SPDX-License-Identifier: MIT
 */

import React from "react";

// React-Searchkit ships a separate, incomplete Portuguese catalog. Use its
// extension point to localize this UI subtree while preserving input values,
// event handlers, validation and range calculations from the original component.
function localizeRangeNode(node) {
  const translate = (text) => window.argiloT ? window.argiloT(text) : text;
  if (typeof node === "string") return translate(node);
  if (!React.isValidElement(node)) return node;
  const props = {};
  for (const attribute of ["aria-label", "title", "placeholder", "content"]) {
    if (typeof node.props[attribute] === "string") {
      props[attribute] = translate(node.props[attribute]);
    }
  }
  if (node.props.children !== undefined) {
    props.children = React.Children.map(node.props.children, localizeRangeNode);
  }
  return React.cloneElement(node, props);
}

function LocalizedDateRange({ children }) {
  return <>{React.Children.map(children, localizeRangeNode)}</>;
}

export const overriddenComponents = {
  "InvenioAppRdm.Search.RangeFacet.CustomFilter.element": LocalizedDateRange,
};
