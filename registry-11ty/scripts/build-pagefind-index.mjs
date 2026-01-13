import fs from 'fs';
import path from 'path';
import * as pagefind from "pagefind";

async function buildPagefindIndex() {
  console.log('Building PageFind index with custom records...');

  const providers = JSON.parse(fs.readFileSync('src/_data/providers.json', 'utf-8'));
  const modules = JSON.parse(fs.readFileSync('src/_data/modules.json', 'utf-8'));

  const { index } = await pagefind.createIndex({
    writePlayground: true
  });

  let providersAdded = 0;
  let modulesAdded = 0;

  for (const provider of providers.providers) {
    await index.addCustomRecord({
      url: `/providers/${provider.id}/`,
      content: `${provider.name} ${provider.description}`,
      language: 'en',
      meta: {
        type: 'provider',
        name: provider.name,
        description: provider.description,
        providerId: provider.id,
        providerName: provider.name
      },
      filters: {
        type: ['provider']
      }
    });
    providersAdded++;
  }

  for (const module of modules.modules) {
    const url = `/providers/${module.provider_id}/#${module.id}`;

    const content = `${module.name} ${module.name} ${module.name} ${module.short_description} ${module.provider_name} ${module.import_path}`;

    await index.addCustomRecord({
      url: url,
      content: content,
      language: 'en',
      meta: {
        type: 'module',
        className: module.name,
        name: module.name,
        description: module.short_description,
        moduleType: module.type,
        importPath: module.import_path,
        modulePath: module.module_path,
        providerName: module.provider_name,
        providerId: module.provider_id
      },
      filters: {
        type: ['module'],
        moduleType: [module.type],
        providerId: [module.provider_id]
      }
    });
    modulesAdded++;
  }

  await index.writeFiles({
    outputPath: './_site/pagefind'
  });

  await index.deleteIndex();

  // clean up once complete
  await pagefind.close();

  console.log(`✓ Built PageFind index with ${providersAdded + modulesAdded} custom records`);
  console.log(`  - ${providersAdded} providers`);
  console.log(`  - ${modulesAdded} modules`);
}

buildPagefindIndex().catch(console.error);
