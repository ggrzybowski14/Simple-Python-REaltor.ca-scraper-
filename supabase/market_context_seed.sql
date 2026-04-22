insert into public.market_profiles (
    market_key,
    market_name,
    province,
    geography_type,
    status,
    notes
)
values
    (
        'victoria_bc',
        'Victoria',
        'BC',
        'cma',
        'active',
        'First-pass structured market context seeded from official Statistics Canada pages. CMHC housing fundamentals are read separately from market_reference_data.'
    ),
    (
        'duncan_bc',
        'Duncan',
        'BC',
        'ca',
        'active',
        'First-pass structured market context seeded from official Statistics Canada pages. CMHC housing fundamentals currently use the explicit Victoria proxy already defined in the app when needed.'
    )
on conflict (market_key) do update
set
    market_name = excluded.market_name,
    province = excluded.province,
    geography_type = excluded.geography_type,
    status = excluded.status,
    notes = excluded.notes;

insert into public.market_metrics (
    market_key,
    metric_key,
    value_numeric,
    unit,
    source_name,
    source_url,
    confidence,
    notes
)
values
    (
        'victoria_bc',
        'population',
        397237,
        'people',
        'Statistics Canada 2021 Census',
        'https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0503935&lang=E&topic=1',
        'high',
        'Victoria CMA population in the 2021 Census.'
    ),
    (
        'victoria_bc',
        'population_growth_percent',
        8.0,
        'percent',
        'Statistics Canada 2021 Census',
        'https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0503935&lang=E&topic=1',
        'high',
        'Population change from 2016 to 2021 for Victoria CMA.'
    ),
    (
        'victoria_bc',
        'unemployment_rate_percent',
        6.9,
        'percent',
        'Statistics Canada 2021 Census',
        'https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0503935&lang=E&topic=12',
        'medium',
        'Census unemployment rate for the population aged 15+ in Victoria CMA. This is not the same as the monthly Labour Force Survey series.'
    ),
    (
        'victoria_bc',
        'median_household_income',
        75500,
        'cad',
        'Statistics Canada 2021 Census',
        'https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/Page.cfm?dguid=2021S0503935&lang=e&topic=5',
        'high',
        'Median after-tax household income in 2020 for Victoria CMA.'
    ),
    (
        'duncan_bc',
        'population',
        47582,
        'people',
        'Statistics Canada 2021 Census',
        'https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/Page.cfm?dguid=2021S0504937&lang=E&topic=1',
        'high',
        'Duncan CA population in the 2021 Census.'
    ),
    (
        'duncan_bc',
        'population_growth_percent',
        7.0,
        'percent',
        'Statistics Canada 2021 Census',
        'https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/Page.cfm?dguid=2021S0504937&lang=E&topic=1',
        'high',
        'Population change from 2016 to 2021 for Duncan CA.'
    ),
    (
        'duncan_bc',
        'unemployment_rate_percent',
        7.5,
        'percent',
        'Statistics Canada 2021 Census',
        'https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0504937&lang=E&topic=12',
        'medium',
        'Census unemployment rate for the population aged 15+ in Duncan CA.'
    ),
    (
        'duncan_bc',
        'median_household_income',
        69000,
        'cad',
        'Statistics Canada 2021 Census',
        'https://www12.statcan.gc.ca/census-recensement/2021/as-sa/fogs-spg/page.cfm?dguid=2021S0504937&lang=E&topic=5',
        'high',
        'Median after-tax household income in 2020 for Duncan CA.'
    )
on conflict (market_key, metric_key) do update
set
    value_numeric = excluded.value_numeric,
    unit = excluded.unit,
    source_name = excluded.source_name,
    source_url = excluded.source_url,
    confidence = excluded.confidence,
    notes = excluded.notes;

insert into public.market_metric_series (
    market_key,
    series_key,
    point_date,
    value_numeric,
    unit,
    source_name,
    source_url,
    confidence,
    notes
)
values
    ('victoria_bc', 'residential_property_price_index_total', '2017-01-01', 95.1, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2017-04-01', 100.2, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2017-07-01', 102.5, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2017-10-01', 102.1, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2018-01-01', 104.7, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2018-04-01', 107.8, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2018-07-01', 107.5, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2018-10-01', 108.2, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2019-01-01', 106.3, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2019-04-01', 109.4, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2019-07-01', 108.6, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2019-10-01', 111.0, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2020-01-01', 111.5, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2020-04-01', 112.0, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2020-07-01', 113.9, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.'),
    ('victoria_bc', 'residential_property_price_index_total', '2020-10-01', 118.3, 'index_2017_100', 'Statistics Canada RPPI', 'https://www150.statcan.gc.ca/n1/daily-quotidien/210208/cg-b007-png-eng.htm', 'high', 'Statistics Canada residential property price index for Victoria, total series.')
on conflict (market_key, series_key, point_date) do update
set
    value_numeric = excluded.value_numeric,
    unit = excluded.unit,
    source_name = excluded.source_name,
    source_url = excluded.source_url,
    confidence = excluded.confidence,
    notes = excluded.notes;
