param([Parameter(Mandatory=$true)][int]$Port)
$ErrorActionPreference = 'Stop'
$lib = Join-Path $env:TEMP 'telemetria-bi-validation'
[void][Reflection.Assembly]::LoadFrom((Join-Path $lib 'Microsoft.AnalysisServices.AdomdClient.dll'))
$connection = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Port")
$connection.Open()
function Query([string]$Dax) {
    $command = $connection.CreateCommand()
    $command.CommandText = $Dax
    $reader = $command.ExecuteReader()
    $result = [System.Collections.Generic.List[object]]::new()
    while ($reader.Read()) {
        $row = [ordered]@{}
        for ($i=0; $i -lt $reader.FieldCount; $i++) {
            $name = ($reader.GetName($i) -replace '^.*\[', '') -replace '\]$', ''
            $row[$name] = if ($reader.IsDBNull($i)) { $null } else { $reader.GetValue($i) }
        }
        $result.Add($row)
    }
    $reader.Close()
    return ,$result.ToArray()
}
$metrics = '"Contas", [Contas na base], "Licenciadas", [Contas licenciadas], "Atribuicoes", [Licenças atribuídas], "Revisao", [Contas para revisão]'
$result = [ordered]@{}
$result.totals = Query ('EVALUATE ROW(' + $metrics + ', "Cobertura", [Cobertura])')
$result.groups = Query ('EVALUATE SELECTCOLUMNS(FILTER(SUMMARIZECOLUMNS(DimOrganizacao[Unidade], DimVinculo[Vínculo], DimEmpresa[Empresa], ' + $metrics + '), [Contas] > 0), "Unidade", DimOrganizacao[Unidade], "Vinculo", DimVinculo[Vínculo], "Empresa", DimEmpresa[Empresa], "Contas", [Contas], "Licenciadas", [Licenciadas], "Atribuicoes", [Atribuicoes], "Revisao", [Revisao])')
$result.products = Query 'EVALUATE SUMMARIZECOLUMNS(DimOrganizacao[Unidade], DimProduto[Produto], "Contas", [Contas na base], "Licenciadas", [Contas licenciadas], "Atribuicoes", [Licenças atribuídas], "Cobertura", [Cobertura])'
$result.review = Query 'EVALUATE SELECTCOLUMNS(FILTER(FatoContas, FatoContas[Revisar] = 1), "UPN", FatoContas[UPN], "Motivo", FatoContas[Motivo da revisão]) ORDER BY [UPN]'
$result.empty = Query ('EVALUATE CALCULATETABLE(ROW(' + $metrics + ', "Cobertura", [Cobertura]), DimOrganizacao[Unidade] = "__SEM_CORRESPONDENCIA__")')
$result.profiles = Query 'EVALUATE SUMMARIZECOLUMNS(DimCombinacao[Produtos], "Contas", [Contas na base], "Licencas", [Licenças atribuídas])'
$result.top10 = Query 'EVALUATE SUMMARIZECOLUMNS(DimOrganizacao[Unidade], "Licencas", [Top 10 unidades]) ORDER BY [Licencas] DESC, DimOrganizacao[Unidade] ASC'
$result.subunitsClosed = Query 'EVALUATE SUMMARIZECOLUMNS(DimOrganizacao[Subunidade], "Contas", [Contas da subunidade])'
$result.subunitsOpen = Query 'EVALUATE SUMMARIZECOLUMNS(DimOrganizacao[Subunidade], TREATAS({"Unidade 074"}, DimOrganizacao[Unidade]), "Contas", [Contas da subunidade], "Licencas", [Licenças da subunidade])'
$result.reviewReason = Query 'EVALUATE CALCULATETABLE(ROW("Contas", [Contas para revisão], "Taxa", [Taxa de revisão]), FatoContas[Motivo da revisão] = "Inativa com licença")'
$connection.Close()
$output = Join-Path $lib 'native-results-anonymized.json'
$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $output -Encoding UTF8
Write-Output $output
