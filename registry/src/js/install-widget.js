/*!
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

// Install tool preference persistence
(function() {
  const widget = document.querySelector('.install .widget');
  if (!widget) return;

  const radios = widget.querySelectorAll('input[type="radio"][name="install-tool"]');

  // Restore saved preference
  const savedTool = localStorage.getItem('installTool');
  if (savedTool) {
    const savedRadio = widget.querySelector(`input[value="${savedTool}"]`);
    if (savedRadio) {
      savedRadio.checked = true;
    }
  }

  // Save preference on change
  radios.forEach(radio => {
    radio.addEventListener('change', () => {
      if (radio.checked) {
        localStorage.setItem('installTool', radio.value);
      }
    });
  });
})();
